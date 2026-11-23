"""Forge-owned gateway. All administration travels over the desktop parent's private stdin pipe."""

import asyncio
import contextlib
import hmac
import ipaddress
import json
import secrets
import socket
import sys
import time
from pathlib import Path

import aiohttp
from aiohttp import web
from core.auth_service import auth_tokens, jwt_expiration

from core.constants import CONFIG_DIR
from core.gateway_accounts import Scheduler, read_accounts
from core.gateway_client_bundle import export_client_bundle
from core.gateway_launch import prepare_launch
from core.gateway_protocol import Protocol
from core.gateway_store import GatewayStore, digest
from core.gateway_tls import server_tls
from core.profile_service import get_active_auth_path


LOCAL_OWNER = {"id": "local", "name": "本机", "cap": 8}


def addresses():
    nets = [ipaddress.ip_network(s) for s in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")]
    try:
        interfaces = socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)
    except socket.gaierror:
        return []
    return sorted(
        {entry[4][0] for entry in interfaces if any(ipaddress.ip_address(entry[4][0]) in net for net in nets)}
    )


class Gateway:
    def __init__(self, store, account_source=read_accounts):
        self.store, self.account_source = store, account_source
        self.snapshot = []
        self.refreshed = -100.0
        self.scheduler = Scheduler(self.accounts)
        self.client = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=None, sock_connect=15, sock_read=180),
            trust_env=True,
            cookie_jar=aiohttp.DummyCookieJar(),
        )
        self.proto = Protocol(store, self.scheduler, self.client, store.identify, self.identify_local)
        self.listeners = {}
        self.drain = set()
        self.error = ""
        self.port = int(store.option("port", 19380))
        self.lan_port = int(store.option("lanPort", 19381))
        self.address = store.option("address", "")
        self.local_key_hash = digest(self.local_key()) if store.option("localKey") else ""
        self.local_chatgpt = store.option("localChatgpt") is True
        self.housekeeping = asyncio.create_task(self.purge_expired())

    async def purge_expired(self):
        while True:
            await asyncio.sleep(60)
            self.store.purge()

    def local_key(self):
        return self.store.secret("localKey", lambda: ("fg_" + secrets.token_urlsafe(32)).encode()).decode()

    def identify_local(self, bearer):
        if self.local_key_hash and hmac.compare_digest(digest(bearer), self.local_key_hash):
            return LOCAL_OWNER.copy()
        if self.local_chatgpt:
            try:
                auth = json.loads(get_active_auth_path().read_text(encoding="utf-8-sig"))
            except (OSError, ValueError):
                return None
            token = (auth_tokens(auth) or {}).get("access_token")
            if isinstance(token, str) and (jwt_expiration(token) or 0) > time.time() and hmac.compare_digest(
                digest(bearer), digest(token)
            ):
                return LOCAL_OWNER.copy()
        return None

    def accounts(self):
        if time.monotonic() - self.refreshed > 2:
            self.snapshot = self.account_source(self.store.policies())
            self.refreshed = time.monotonic()
        return self.snapshot

    async def listen(self, local, address, port):
        if local in self.listeners:
            return

        def accepting():
            return self.listeners.get(local, (None, None))[1] is runner

        runner = web.AppRunner(
            self.proto.app(local, accepting), access_log=None, handler_cancellation=True, shutdown_timeout=120
        )
        await runner.setup()
        try:
            site = web.TCPSite(runner, address, port, ssl_context=server_tls(self.store, address))
            await site.start()
        except BaseException:
            await runner.cleanup()
            raise
        self.listeners[local] = (site, runner)
        self.scheduler.accepting = True
        self.error = ""

    async def unlisten(self, local):
        if local not in self.listeners:
            return
        site, runner = self.listeners.pop(local)
        await site.stop()

        # Existing streams have bounded time to finish. Stop idle WS sockets admitting new turns.
        async def drain():
            idle = [
                ws
                for ws, (_, application) in self.proto.sockets.items()
                if application is runner.app and ws not in self.proto.generating
            ]
            await asyncio.gather(
                *(ws.close(code=1001, message=b"listener stopped") for ws in idle), return_exceptions=True
            )
            await runner.cleanup()

        task = asyncio.create_task(drain())
        self.drain.add(task)
        task.add_done_callback(self.drain.discard)

    async def start(self):
        await self.listen(True, "127.0.0.1", self.port)
        self.store.set_option("enabled", True)

    async def restore(self):
        if self.store.option("enabled", False):
            try:
                await self.start()
                if self.store.option("shared", False):
                    await self.share(self.address, self.lan_port)
            except (OSError, ValueError) as exc:
                self.error = str(exc)

    async def share(self, address, port):
        if address not in addresses() or not 1 <= port <= 65535:
            raise ValueError("请选择本机的局域网 IPv4 地址和有效端口")
        if False in self.listeners and (address, port) != (self.address, self.lan_port):
            raise ValueError("更换地址前请先关闭局域网共享")
        await self.start()
        await self.listen(False, address, port)
        self.address, self.lan_port = address, port
        for k, v in (("address", address), ("lanPort", port), ("shared", True)):
            self.store.set_option(k, v)

    def status(self):
        active = self.scheduler.active
        keys = self.store.list_keys()
        if self.local_key_hash:
            keys.insert(0, {**LOCAL_OWNER, "enabled": True, "expires": 0, "calls": self.store.option("localCalls", 0)})
        return {
            "enabled": True in self.listeners,
            "shared": False in self.listeners,
            "base": f"https://127.0.0.1:{self.port}/v1",
            "address": self.address,
            "port": self.lan_port,
            "lanBase": f"https://{self.address}:{self.lan_port}/v1" if self.address else "",
            "ca": str(self.store.directory / "forge-gateway-ca.pem"),
            "addresses": addresses(),
            "keys": [
                {
                    **k,
                    "active": self.scheduler.owner_active[k["id"]],
                    "waiting": len(self.scheduler.waiters.get(k["id"], ())),
                }
                for k in keys
            ],
            "waiting": self.scheduler.waiting,
            "error": self.error,
            "active": sum(active.values()),
            "records": list(self.proto.records),
            "accounts": [
                {
                    "id": a.id,
                    "name": a.name,
                    "cap": a.cap,
                    "enabled": a.enabled,
                    "active": active[a.id],
                    "reason": (a.reason if a.token_expired else "")
                    or ("等待额度恢复后续写" if a.id in self.proto.quota_waiting.values() else "") or a.reason
                    or ("冷却中" if self.scheduler.cooldown.get(a.id, 0) > time.monotonic() else ""),
                }
                for a in self.accounts()
            ],
        }

    async def command(self, cmd, p) -> dict[str, object]:
        if cmd == "status":
            return self.status()
        if cmd == "service":
            if p["enabled"]:
                await self.start()
            else:
                self.scheduler.accepting = False
                self.scheduler.changed.set()
                await self.unlisten(False)
                await self.unlisten(True)
                self.store.set_option("shared", False)
                self.store.set_option("enabled", False)
                self.error = ""
        elif cmd == "share":
            if p["enabled"]:
                await self.share(str(p["address"]), int(p["port"]))
            else:
                await self.unlisten(False)
                self.store.set_option("shared", False)
        elif cmd == "export_client_bundle":
            if False not in self.listeners:
                raise ValueError("请先开启局域网共享")
            export_client_bundle(
                p["destination"], f"https://{self.address}:{self.lan_port}/v1",
                self.store.directory / "forge-gateway-ca.pem", p["script"],
            )
            return {"saved": True}
        elif cmd == "key":
            result = self.store.change_key(p["action"], p)
            self.scheduler.changed.set()
            return result
        elif cmd == "policy":
            pid, cap = str(p["id"]), int(p["cap"])
            if not 1 <= cap <= 32 or not any(a.id == pid for a in self.accounts()):
                raise ValueError("无效的账号或并发上限")
            self.store.db.execute(
                "INSERT OR REPLACE INTO policies VALUES(?,?,?)", (pid, bool(p["enabled"]), cap)
            )
            self.refreshed = -100
            self.scheduler.changed.set()
        elif cmd == "launch":
            if not any(self.scheduler.eligible(a) for a in self.accounts()):
                raise ValueError("没有可用账号，请前往「负载均衡」检查并启用参与调度的账号")
            key = self.local_key()
            self.local_key_hash = digest(key)
            plan = await asyncio.to_thread(
                prepare_launch,
                f"https://127.0.0.1:{self.port}/v1",
                self.store.directory / "forge-gateway-ca.pem",
                key,
            )
            was_running = True in self.listeners
            await self.start()
            previous_login = self.local_chatgpt
            try:
                self.store.set_option("localChatgpt", plan.native_auth)
                self.local_chatgpt = plan.native_auth
                return await asyncio.to_thread(plan.start)
            except Exception:
                self.local_chatgpt = previous_login
                self.store.set_option("localChatgpt", previous_login)
                if not was_running:
                    await self.command("service", {"enabled": False})
                raise
        else:
            raise ValueError("未知网关操作")
        return self.status()

    async def close(self):
        self.housekeeping.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.housekeeping
        self.scheduler.accepting = False
        self.scheduler.changed.set()
        await self.unlisten(False)
        await self.unlisten(True)
        if self.drain:
            await asyncio.gather(*self.drain, return_exceptions=True)
        await self.client.close()
        self.store.db.close()


async def serve():
    g = Gateway(GatewayStore(CONFIG_DIR / "gateway"))
    try:
        await g.restore()
        while line := await asyncio.to_thread(sys.stdin.buffer.readline):
            msg = {}
            try:
                msg = json.loads(line)
                value = await g.command(msg["command"], msg.get("payload", {}))
                result = {"ok": True, "data": value, "error": ""}
            except Exception as exc:  # noqa: BLE001 - isolate each desktop IPC command
                result = {"ok": False, "data": {}, "error": str(exc)}
            print(json.dumps({"id": msg.get("id"), **result}, ensure_ascii=False), flush=True)
    finally:
        await g.close()
