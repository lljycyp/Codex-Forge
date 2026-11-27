import asyncio
import base64
import json
import sqlite3
import ssl
import tempfile
import threading
import time
import unittest
from contextlib import AsyncExitStack
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from zipfile import ZipFile

from aiohttp import ClientSession, TCPConnector, WSServerHandshakeError, web
from aiohttp.test_utils import TestServer
from core.gateway import Gateway
from core.gateway_accounts import Account
from core.gateway_launch import (
    BALANCED_CHATGPT_FLAG, BALANCED_FLAG, OVERRIDE, prepare_launch, workspace_startup_failure,
)
from core.gateway_store import GatewayStore


class GatewayDesktopLaunch(unittest.TestCase):
    def test_workspace_failure_is_scoped_to_the_launched_process_and_startup(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            day = root / "Packages" / "OpenAI.Codex_test" / "LocalCache/Local/Codex/Logs/2026/11/25"
            day.mkdir(parents=True)
            warning = " warning sa_server_request_failed routePattern="
            expected = "2026-11-25T02:49:45.793Z" + warning + "/accounts/check/{version} status=432"
            (day / "codex-desktop-test-13100-t0-i1-024933-0.log").write_text(
                "\n".join((
                    "2026-11-25T02:40:45Z" + warning + "/settings/user status=403",
                    expected,
                    "2026-11-25T02:49:46Z" + warning + "/pins status=403",
                    "2026-11-25T03:49:45Z" + warning + "/settings/user status=403",
                )),
                encoding="utf-8",
            )
            (day / "codex-desktop-test-13000-t0-i1-024933-0.log").write_text(
                "2026-11-25T02:49:46Z" + warning + "/settings/user status=403",
                encoding="utf-8",
            )
            started_at = datetime.fromisoformat("2026-11-25T02:49:33Z").timestamp()
            self.assertEqual(workspace_startup_failure(root, 13100, started_at), {
                "at": datetime.fromisoformat("2026-11-25T02:49:45.793Z").timestamp(),
                "route": "/accounts/check/{version}",
                "status": 432,
            })

    def test_running_client_refused_before_touching_home_or_starting_gateway(self):
        with (
            patch("bridge.commands.load_config", return_value={"codex_skin_enabled": True}),
            patch("bridge.commands._running_codex_count", return_value=1),
            patch("bridge.commands._resolve_codex_app_source_path") as resolve,
            patch("bridge.commands._stop_running_codex_processes") as stop,
        ):
            with self.assertRaisesRegex(ValueError, "Codex 正在运行"):
                prepare_launch("https://localhost/v1", "ca.pem", "fg-test")
            resolve.assert_not_called()
            stop.assert_not_called()

    def test_balanced_launch_uses_separate_login_and_shares_history(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            system_home = root / "system"
            system_home.mkdir()
            auth = system_home / "auth.json"
            original_auth = '{"OPENAI_API_KEY":"system-key"}'
            auth.write_text(original_auth, encoding="utf-8")
            original_config = 'model = "test-model"\n'
            (system_home / "config.toml").write_text(original_config, encoding="utf-8")
            (root / "resources").mkdir()
            (root / "resources" / "codex.exe").touch()
            (root / "resources" / "app.asar").write_bytes(OVERRIDE.encode())
            with (
                patch.dict("os.environ", {"CODEX_HOME": str(system_home), "OPENAI_API_KEY": "system-env-key"}),
                patch("bridge.commands.load_config", return_value={"launch_mode": "multi", "active_profile": "work", "codex_skin_enabled": True}),
                patch("bridge.commands._running_codex_count", return_value=0),
                patch("bridge.commands.db.load_profile_launch_settings", return_value={}),
                patch("bridge.commands._resolve_codex_app_source_path", return_value=root / "Codex.exe"),
                patch("bridge.commands._get_shared_app_root", return_value=root / "locks"),
                patch("bridge.commands._allocate_codex_skin_port", return_value=19335),
                patch("core.gateway_launch.resolve_codex_execution_path", return_value=root / "Codex.exe"),
                patch("core.gateway_launch.subprocess.Popen") as spawn,
                patch("core.gateway_launch._login_gateway") as login,
            ):
                spawn.return_value.pid = 789
                url = "https://127.0.0.1:19380/v1"
                plan = prepare_launch(url, root / "ca.pem", "fg-test")
                gateway_home = Path(plan.env["CODEX_HOME"])
                self.assertFalse(plan.native_auth)
                self.assertNotEqual(gateway_home, system_home)
                self.assertEqual(Path(plan.env["CODEX_SQLITE_HOME"]), system_home)
                self.assertEqual((gateway_home / "sessions").resolve(), (system_home / "sessions").resolve())
                self.assertEqual((gateway_home / "archived_sessions").resolve(), (system_home / "archived_sessions").resolve())
                self.assertEqual(auth.read_text(encoding="utf-8"), original_auth)
                self.assertEqual((system_home / "config.toml").read_text(encoding="utf-8"), original_config)
                self.assertNotIn("OPENAI_API_KEY", plan.env)
                self.assertEqual(plan.env[OVERRIDE], url)
                login.assert_called_once_with(gateway_home, root / "resources" / "codex.exe", plan.env, url, "fg-test")
                self.assertFalse(any(arg.startswith("--user-data-dir") for arg in plan.command))
                self.assertIn(BALANCED_FLAG, plan.command)
                self.assertIn("--remote-debugging-address=127.0.0.1", plan.command)
                self.assertIn("--remote-debugging-port=19335", plan.command)
                self.assertEqual(
                    plan.start()["skinSession"], {"profileName": "work", "port": 19335, "processId": 789}
                )

    def test_chatgpt_launch_syncs_the_native_workspace_before_spawning(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp).resolve()
            home = root / "system"
            home.mkdir()
            auth = home / "auth.json"
            auth.write_text('{"tokens":{"access_token":"test"}}', encoding="utf-8")
            config_path = home / "config.toml"
            config_path.write_text('model = "test-model"\n', encoding="utf-8")
            (root / "resources").mkdir()
            (root / "resources" / "app.asar").write_text(OVERRIDE, encoding="utf-8")
            config = {"codex_skin_enabled": False}
            order = []

            def start_process(*args, **kwargs):
                order.append("spawn")
                return SimpleNamespace(pid=789)

            with (
                patch.dict("os.environ", {"CODEX_HOME": str(home), "CODEX_SQLITE_HOME": str(home), "NO_PROXY": "example.test"}),
                patch("bridge.commands.load_config", return_value=config),
                patch("bridge.commands._running_codex_count", return_value=0),
                patch("bridge.commands._resolve_codex_app_source_path", return_value=root / "Codex.exe"),
                patch("bridge.commands._get_shared_app_root", return_value=root / "locks"),
                patch("bridge.commands.get_active_auth_path", return_value=auth),
                patch("bridge.commands._sync_shared_workspace", side_effect=lambda *args: order.append("sync")) as sync,
                patch("core.gateway_launch.get_active_codex_dir", return_value=home),
                patch("core.gateway_launch.resolve_codex_execution_path", return_value=root / "Codex.exe"),
                patch("core.gateway_launch.subprocess.Popen", side_effect=start_process),
                patch("core.gateway_launch._login_gateway") as login,
            ):
                plan = prepare_launch("https://127.0.0.1:19380/v1", root / "ca.pem", "fg-test")
                self.assertTrue(plan.native_auth)
                self.assertEqual(plan.env["CODEX_HOME"], str(home))
                self.assertEqual(plan.env["CODEX_SQLITE_HOME"], str(home))
                self.assertEqual(plan.env["NO_PROXY"], "example.test,127.0.0.1")
                self.assertIn(BALANCED_CHATGPT_FLAG, plan.command)
                self.assertFalse(any(arg.startswith("--remote-debugging-") for arg in plan.command))
                login.assert_not_called()
                sync.assert_not_called()
                self.assertEqual(plan.start(), {"pid": 789})
                self.assertEqual(order, ["sync", "spawn"])
                sync.assert_called_once_with(config, home, auth)
                self.assertFalse((root / "codex-home").exists())
                self.assertEqual(auth.read_text(encoding="utf-8"), '{"tokens":{"access_token":"test"}}')
                self.assertEqual(config_path.read_text(encoding="utf-8"), 'model = "test-model"\n')


class GatewayIntegration(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.seen = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

        async def upstream(request):
            payload = await request.json()
            self.seen.append((request.headers["Authorization"], payload))
            if payload.get("model") == "hold":
                self.started.set()
                await self.release.wait()
            rid = "resp_" + str(len(self.seen))
            item = {
                "id": rid + "item",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "reply"}],
            }
            events = [
                {"type": "response.output_item.done", "output_index": 0, "item": item},
                {"type": "response.completed", "response": {"id": rid, "status": "completed", "output": []}},
            ]
            return web.Response(
                content_type="text/event-stream",
                body=b"".join(b"data: " + json.dumps(event).encode() + b"\r\n\r\n" for event in events),
            )

        app = web.Application()
        app.router.add_post("/responses", upstream)
        self.origin = TestServer(app)
        await self.origin.start_server()
        self.accounts = [
            Account(
                i,
                i,
                1,
                True,
                base=str(self.origin.make_url("")).rstrip("/"),
                headers={"Authorization": "Bearer upstream-" + i},
            )
            for i in ("A", "B")
        ]
        self.store = GatewayStore(Path(self.temp.name))
        self.gateway = Gateway(self.store, lambda policies: self.accounts)
        self.gateway.port = 0
        await self.gateway.start()
        _, runner = self.gateway.listeners[True]
        self.base = f"https://127.0.0.1:{runner.addresses[0][1]}/v1"
        self.keys = [self.store.change_key("create", {"name": i, "cap": 1}) for i in ("one", "two")]
        ctx = ssl.create_default_context(cafile=str(self.store.directory / "forge-gateway-ca.pem"))
        self.client = ClientSession(connector=TCPConnector(ssl=ctx, limit=0))

    async def asyncTearDown(self):
        self.release.set()
        await self.client.close()
        await self.gateway.close()
        await self.origin.close()
        self.temp.cleanup()

    def headers(self, n=0):
        return {"Authorization": "Bearer " + self.keys[n]["key"]}

    async def post(self, body, n=0):
        async with self.client.post(self.base + "/responses", headers=self.headers(n), json=body) as r:
            return r.status, await r.json()

    async def test_gateway_record_leaves_unreported_token_counts_unknown(self):
        status, _ = await self.post({"input": "hello"})
        self.assertEqual(status, 200)
        row = self.gateway.status()["records"][0]
        self.assertEqual(row["continuations"], 0)
        for field in ("inputTokens", "cachedTokens", "outputTokens"):
            self.assertNotIn(field, row)

    async def test_models_403_reports_selected_account_and_sanitized_rejection(self):
        async def models(request):
            if request.headers["Authorization"] == "Bearer upstream-A":
                return web.Response(text='<p>Unable to load site</p> private upstream data', status=403)
            return web.json_response({"error": {"code": "account_deactivated", "message": "private upstream data"}}, status=403)

        app = web.Application()
        app.router.add_get("/models", models)
        async with TestServer(app) as origin:
            for account, reason, code in (
                (self.accounts[0], "site_block", "upstream_error"),
                (self.accounts[1], "provider_error", "account_deactivated"),
            ):
                for candidate in self.accounts:
                    candidate.enabled = candidate is account
                    candidate.base = str(origin.make_url("")).rstrip("/")
                with patch("core.gateway_protocol.logger.warning") as warning:
                    async with self.client.get(self.base + "/models", headers=self.headers()) as response:
                        self.assertEqual(response.status, 403)
                        self.assertNotIn("private upstream data", await response.text())
                diagnostic = self.gateway.status()["lastUpstreamForbidden"]
                self.assertEqual((diagnostic["account"], diagnostic["reason"], diagnostic["code"]), (account.name, reason, code))
                self.assertEqual(diagnostic["operation"], "GET /v1/models")
                self.assertEqual(warning.call_args.args[1:], (account.name, account.id, "GET /v1/models", reason, code))

    async def test_websocket_upstream_handshake_403_distinguishes_challenge(self):
        async def reject(_request):
            return web.Response(status=403, headers={"cf-mitigated": "challenge"})

        app = web.Application()
        app.router.add_get("/responses", reject)
        async with TestServer(app) as origin:
            self.accounts[1].enabled = False
            self.accounts[0].base = str(origin.make_url("")).rstrip("/")
            async with self.client.ws_connect(self.base + "/responses", headers=self.headers()) as ws:
                await ws.send_json({"type": "response.create", "model": "test", "input": "hello"})
                event = await ws.receive_json(timeout=5)
                self.assertEqual(event["type"], "error")
            diagnostic = self.gateway.status()["lastUpstreamForbidden"]
            self.assertEqual(diagnostic["account"], "A")
            self.assertEqual(diagnostic["reason"], "site_block")
            self.assertEqual(diagnostic["operation"], "WS /v1/responses")

    async def test_websocket_request_logs_distinct_upstream_502_sources(self):
        async def websocket(request):
            if scenario == "fallback":
                return web.Response(status=405)
            if scenario == "handshake":
                return web.Response(status=502)
            ws = web.WebSocketResponse()
            await ws.prepare(request)
            await ws.receive_json()
            await ws.close(code=1011, message=b"private close reason")
            return ws

        async def post(_request):
            return web.json_response(
                {"error": {"type": "invalid_request_error", "message": "private upstream data"}},
                status=502,
            )

        app = web.Application()
        app.router.add_get("/responses", websocket)
        app.router.add_post("/responses", post)
        async with TestServer(app) as origin:
            self.accounts[1].enabled = False
            self.accounts[0].base = str(origin.make_url("")).rstrip("/")
            for scenario, diagnostic in (
                (
                    "disconnect",
                    "来源=上游WebSocket断开 账号='A' 账号ID='A' 请求=WS /v1/responses 帧类型=CLOSE 关闭码=1011",
                ),
                ("handshake", "来源=上游WebSocket握手HTTP响应 账号='A' 账号ID='A' 请求=WS /v1/responses"),
                (
                    "fallback",
                    "来源=上游HTTP响应 账号='A' 账号ID='A' 请求=POST /v1/responses 上游错误码=invalid_request_error",
                ),
            ):
                self.gateway.scheduler.cooldown.clear()
                with self.subTest(scenario=scenario), self.assertLogs("core.gateway_protocol", "WARNING") as logs:
                    async with self.client.ws_connect(self.base + "/responses", headers=self.headers()) as ws:
                        await ws.send_json({"type": "response.create", "model": "test", "input": "private input"})
                        event = await ws.receive_json(timeout=5)
                        self.assertEqual((event["type"], event["code"]), ("error", "invalid_request_error"))
                    self.assertEqual(self.gateway.status()["records"][0]["result"], "502 invalid_request_error")
                    self.assertEqual([record.getMessage() for record in logs.records], ["网关 502 " + diagnostic])

    async def test_switch_configures_live_gateway_before_desktop_launch(self):
        await self.gateway.unlisten(True)
        ca = self.store.directory / "forge-gateway-ca.pem"
        ca.unlink()
        with patch("core.gateway.prepare_launch") as prepare:
            prepare.return_value.native_auth = False
            config = await self.gateway.command("prepare_launch", {})
            prepare.return_value.start.assert_not_called()
        key = self.gateway.local_key()
        self.assertEqual(config, {"base": "https://127.0.0.1:0/v1", "ca": str(ca)})
        prepare.assert_called_once_with(config["base"], ca, key)
        self.assertTrue(ca.is_file())
        _, runner = self.gateway.listeners[True]
        url = f"https://127.0.0.1:{runner.addresses[0][1]}/v1/responses"
        async with self.client.post(url, headers={"Authorization": "Bearer " + key}, json={"input": "hello"}) as r:
            self.assertEqual(r.status, 200)
            await r.read()

        self.gateway.port = 19385
        with (
            patch("core.gateway.prepare_launch") as prepare,
            patch.object(self.gateway, "start", new_callable=AsyncMock),
        ):
            prepare.return_value.native_auth = False
            await self.gateway.command("launch", {})
            prepare.return_value.start.assert_called_once()
        self.assertEqual(prepare.call_args.args[:2], ("https://127.0.0.1:19385/v1", ca))

    async def test_switch_reports_listener_failure_without_opening_desktop(self):
        await self.gateway.unlisten(True)
        with (
            patch("core.gateway.prepare_launch") as prepare,
            patch.object(self.gateway, "start", side_effect=OSError("port already in use")),
            self.assertRaisesRegex(OSError, "port already in use"),
        ):
            await self.gateway.command("prepare_launch", {})
        self.assertNotIn(True, self.gateway.listeners)
        self.assertFalse(self.gateway.local_chatgpt)
        prepare.return_value.start.assert_not_called()

    async def test_balanced_key_routes_locally_and_survives_gateway_restart(self):
        with patch("core.gateway.prepare_launch") as prepare:
            prepare.return_value.native_auth = False
            await self.gateway.command("launch", {})
        key = self.gateway.local_key()
        self.assertEqual(prepare.call_args.args[-1], key)
        self.assertNotIn(key, str(self.store.option("localKey")))
        self.accounts[1].enabled = False
        headers = {"Authorization": "Bearer " + key}
        url = self.base + "/responses"

        async def post_local(model):
            async with self.client.post(url, headers=headers, json={"model": model, "input": "test"}) as response:
                await response.read()
                return response.status

        first = asyncio.create_task(post_local("hold"))
        await asyncio.wait_for(self.started.wait(), 3)
        second = asyncio.create_task(post_local("m"))
        try:
            async with asyncio.timeout(3):
                while not self.gateway.scheduler.waiting:
                    await asyncio.sleep(0.01)
            local, lan_key, _ = self.gateway.status()["keys"]
            self.assertEqual((local["id"], local["cap"]), ("local", 8))
            self.assertEqual((local["active"], local["waiting"], local["calls"]), (1, 1, 0))
            self.assertEqual((lan_key["active"], lan_key["waiting"], lan_key["calls"]), (0, 0, 0))
        finally:
            self.release.set()
            results = await asyncio.wait_for(asyncio.gather(first, second), 3)
        self.assertEqual(results, [200, 200])
        self.assertEqual(self.gateway.proto.records[0]["owner"], "本机")
        self.assertEqual(self.seen[0][0], "Bearer upstream-A")

        restarted = Gateway(GatewayStore(self.store.directory), lambda _: self.accounts)
        try:
            self.assertEqual(restarted.identify_local(key), {"id": "local", "name": "本机", "cap": 8, "websocketLimit": 32})
            local = restarted.status()["keys"][0]
            self.assertEqual((local["active"], local["waiting"], local["calls"]), (0, 0, 2))
        finally:
            await restarted.close()
        await self.gateway.listen(False, "127.0.0.1", 0)
        _, runner = self.gateway.listeners[False]
        lan = f"https://127.0.0.1:{runner.addresses[0][1]}/v1/responses"
        async with self.client.post(lan, headers=headers, json={"model": "m", "input": "test"}) as response:
            self.assertEqual(response.status, 401)

    async def test_native_desktop_accepts_only_current_chatgpt_token_on_loopback(self):
        def token(expires_at):
            claims = base64.urlsafe_b64encode(json.dumps({"exp": expires_at}).encode()).decode().rstrip("=")
            return "fixture." + claims + ".fixture"

        auth = self.store.directory / "system-auth.json"
        current = token(int(time.time()) + 3600)
        expired = token(int(time.time()) - 1)

        def write(value):
            auth.write_text(json.dumps({"tokens": {"access_token": value}}), encoding="utf-8")

        async def post(url, value):
            async with self.client.post(url, headers={"Authorization": "Bearer " + value}, json={"model": "m"}) as reply:
                await reply.read()
                return reply.status

        write(current)
        local = self.base + "/responses"
        with (
            patch("core.gateway.get_active_auth_path", return_value=auth),
            patch("core.gateway.prepare_launch") as prepare,
        ):
            self.assertEqual(await post(local, current), 401)
            prepare.return_value.native_auth = True
            await self.gateway.command("launch", {})
            self.assertTrue(self.store.option("localChatgpt"))
            self.assertEqual(await post(local, current), 200)
            self.assertEqual(self.seen[0][0], "Bearer upstream-A")

            await self.gateway.listen(False, "127.0.0.1", 0)
            _, runner = self.gateway.listeners[False]
            lan = f"https://127.0.0.1:{runner.addresses[0][1]}/v1/responses"
            self.assertEqual(await post(lan, current), 401)

            restarted = Gateway(GatewayStore(self.store.directory), lambda _: self.accounts)
            try:
                self.assertEqual(restarted.identify_local(current), {"id": "local", "name": "本机", "cap": 8, "websocketLimit": 32})
                write(expired)
                self.assertIsNone(restarted.identify_local(expired))
                self.assertEqual(await post(local, current), 401)
                self.assertEqual(await post(local, expired), 401)
                newer = token(int(time.time()) + 7200)
                write(newer)
                self.assertEqual(await post(local, newer), 200)
            finally:
                await restarted.close()

            prepare.return_value.native_auth = False
            prepare.return_value.start.side_effect = ValueError("client launch failed")
            with self.assertRaisesRegex(ValueError, "client launch failed"):
                await self.gateway.command("launch", {})
            self.assertTrue(self.store.option("localChatgpt"))
            self.assertEqual(await post(local, newer), 200)

    async def test_ws_handshake_limits_keys_even_above_128_total_connections(self):
        owner = self.keys[0]["id"]
        for index in range(9):
            self.keys.append(self.store.change_key("create", {"name": f"key-{index}", "cap": 1}))
        url = self.base + "/responses"
        async with asyncio.timeout(15), AsyncExitStack() as sockets:
            for index in range(11):
                for _ in range(9 if index == 10 else 12):
                    await sockets.enter_async_context(self.client.ws_connect(url, headers=self.headers(index)))
            with self.assertLogs("core.gateway_protocol", level="WARNING") as logs:
                async with self.client.get(url, headers=self.headers()) as response:
                    self.assertEqual(response.status, 429)
                    self.assertEqual((await response.json())["error"]["code"], "capacity")
            status = await self.gateway.command("status", {})
            websocket = status["websocket"]
            self.assertEqual(websocket["connections"], 129)
            self.assertNotIn("limit", websocket)
            key = next(key for key in status["keys"] if key["id"] == owner)
            self.assertEqual((key["websocketConnections"], key["websocketLimit"]), (12, 12))
            rejection = websocket["lastRejection"]
            self.assertGreater(rejection["at"], 0)
            self.assertEqual((rejection["ownerId"], rejection["ownerName"]), (owner, "one"))
            self.assertEqual(
                (rejection["keyConnections"], rejection["keyLimit"], rejection["totalConnections"]),
                (12, 12, 129),
            )
            self.assertEqual(
                [record.getMessage() for record in logs.records],
                [f"WebSocket 握手拒绝 HTTP 429 key_id={owner} key_connections=12/12 total_connections=129"],
            )

    async def test_local_ws_allows_32_connections_before_rejecting(self):
        with patch("core.gateway.prepare_launch") as prepare:
            prepare.return_value.native_auth = False
            await self.gateway.command("prepare_launch", {})
        headers = {"Authorization": "Bearer " + self.gateway.local_key()}
        url = self.base + "/responses"
        async with AsyncExitStack() as sockets:
            for _ in range(32):
                await sockets.enter_async_context(self.client.ws_connect(url, headers=headers))
            with self.assertRaises(WSServerHandshakeError) as rejected:
                await self.client.ws_connect(url, headers=headers)
            self.assertEqual(rejected.exception.status, 429)

            status = self.gateway.status()
            local = status["keys"][0]
            self.assertEqual((local["id"], local["websocketConnections"], local["websocketLimit"]), ("local", 32, 32))
            self.assertEqual((local["active"], local["cap"]), (0, 8))
            rejection = status["websocket"]["lastRejection"]
            self.assertEqual((rejection["keyConnections"], rejection["keyLimit"]), (32, 32))

    async def test_edit_key_updates_name_and_live_handshake_limit(self):
        key = self.keys[0]
        url = self.base + "/responses"
        payload = {"action": "edit", "id": key["id"], "name": "  renamed  ", "cap": 2, "websocketLimit": 1}
        async with self.client.ws_connect(url, headers=self.headers()) as ws:
            for invalid in (0, -1, 1.5, True, None, 2**53):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                    await self.gateway.command("key", {**payload, "websocketLimit": invalid})
            with self.assertRaises(ValueError):
                await self.gateway.command("key", {**payload, "name": " "})
            original = self.gateway.status()["keys"][0]
            self.assertEqual((original["name"], original["cap"], original["websocketLimit"]), ("one", 1, 12))

            await self.gateway.command("key", payload)
            await ws.send_json({"type": "response.create", "input": "hello", "generate": False})
            self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.created")
            self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.completed")
            with self.assertRaises(WSServerHandshakeError) as rejected:
                await self.client.ws_connect(url, headers=self.headers())
            self.assertEqual(rejected.exception.status, 429)
            status = self.gateway.status()
            updated = status["keys"][0]
            self.assertEqual((updated["name"], updated["cap"], updated["websocketLimit"]), ("renamed", 2, 1))
            self.assertEqual(status["websocket"]["lastRejection"]["ownerName"], "renamed")

        reopened = GatewayStore(self.store.directory)
        try:
            saved = reopened.identify(key["key"])
            assert saved is not None
            self.assertEqual((saved["id"], saved["name"], saved["websocketLimit"]), (key["id"], "renamed", 1))
        finally:
            reopened.db.close()

    async def test_existing_key_gets_default_websocket_limit_on_upgrade(self):
        directory = Path(self.temp.name) / "legacy"
        directory.mkdir()
        db = sqlite3.connect(directory / "gateway.sqlite")
        try:
            with db:
                db.execute(
                    "CREATE TABLE owners(id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT NOT NULL UNIQUE, "
                    "enabled INTEGER NOT NULL, cap INTEGER NOT NULL, expires INTEGER NOT NULL, calls INTEGER NOT NULL DEFAULT 0)"
                )
                db.execute("INSERT INTO owners VALUES('legacy','existing','hash',1,3,0,19)")
        finally:
            db.close()
        upgraded = GatewayStore(directory)
        try:
            key = upgraded.list_keys()[0]
            self.assertEqual((key["name"], key["cap"], key["calls"], key["websocketLimit"]), ("existing", 3, 19, 12))
        finally:
            upgraded.db.close()

    async def test_pending_ws_handshake_reserves_capacity_until_prepare_fails(self):
        await self.gateway.listen(False, "127.0.0.1", 0)
        _, runner = self.gateway.listeners[False]
        shared = f"https://127.0.0.1:{runner.addresses[0][1]}/v1/responses"
        local = self.base + "/responses"
        preparing = asyncio.Event()
        release = asyncio.Event()

        async def fail_prepare(ws, request):
            preparing.set()
            await release.wait()
            raise ValueError("test handshake failure")

        await self.gateway.command("key", {
            "action": "edit", "id": self.keys[0]["id"], "name": "one", "cap": 1, "websocketLimit": 1,
        })
        with patch.object(web.WebSocketResponse, "prepare", fail_prepare):
            first = asyncio.create_task(self.client.get(local, headers=self.headers()))
            try:
                await asyncio.wait_for(preparing.wait(), 3)
                status = self.gateway.status()
                self.assertEqual(status["websocket"]["connections"], 1)
                self.assertEqual(status["keys"][0]["websocketLimit"], 1)
                self.assertEqual(status["keys"][0]["websocketConnections"], 1)
                self.assertEqual(status["keys"][0]["active"], 0)
                async with asyncio.timeout(3):
                    async with self.client.get(shared, headers=self.headers()) as rejected:
                        self.assertEqual(rejected.status, 429)
            finally:
                release.set()
                async with await asyncio.wait_for(first, 3) as failed:
                    self.assertEqual(failed.status, 400)

        self.assertEqual(self.gateway.status()["websocket"]["connections"], 0)
        async with self.client.ws_connect(shared, headers=self.headers(1)):
            self.assertEqual(self.gateway.status()["keys"][1]["websocketConnections"], 1)
        async with asyncio.timeout(3):
            while self.gateway.status()["websocket"]["connections"]:
                await asyncio.sleep(0.01)
            async with self.client.ws_connect(local, headers=self.headers()):
                self.assertEqual(self.gateway.status()["websocket"]["connections"], 1)

    async def test_incremental_ws_across_accounts_and_owners(self):
        initial = {"model": "m", "input": [{"role": "user", "content": "remember this"}]}
        status, first = await self.post(initial)
        self.assertEqual(status, 200)
        self.assertEqual(first["output"][0]["content"][0]["text"], "reply")
        follow = {
            "type": "response.create",
            "model": "m",
            "previous_response_id": first["id"],
            "input": "follow up",
        }
        self.assertEqual((await self.post(follow, 1))[0], 400)
        async with self.client.ws_connect(self.base + "/responses", headers=self.headers()) as ws:
            await ws.send_json(follow)
            await ws.receive_json()
            done = await ws.receive_json()
            self.assertEqual(done["type"], "response.completed")
            self.store.change_key("toggle", {"id": self.keys[0]["id"], "enabled": False})
            await ws.send_json(follow)
            await ws.receive()
            self.assertTrue(ws.closed)
        self.assertEqual([a for a, _ in self.seen], ["Bearer upstream-A", "Bearer upstream-B"])
        next_input = self.seen[-1][1]["input"]
        self.assertEqual([i["role"] for i in next_input], ["user", "assistant", "user"])
        self.assertNotIn("id", next_input[1])
        self.assertNotIn("previous_response_id", self.seen[-1][1])

    async def test_ws_accepts_follow_up_during_previous_turn_cleanup(self):
        cleanup_started = asyncio.Event()
        answer_events = self.gateway.proto.answer_events

        async def slow_cleanup(account, request, wire, websocket, metrics):
            events = answer_events(account, request, wire, websocket, metrics)
            try:
                async for event in events:
                    yield event
            finally:
                if len(self.seen) == 1:
                    cleanup_started.set()
                    await self.release.wait()
                await events.aclose()

        create = {"type": "response.create", "model": "m"}
        with patch.object(self.gateway.proto, "answer_events", slow_cleanup):
            async with self.client.ws_connect(self.base + "/responses", headers=self.headers()) as ws:
                try:
                    await ws.send_json({**create, "input": "original"})
                    await ws.receive_json(timeout=3)
                    first = await ws.receive_json(timeout=3)
                    self.assertEqual(first["type"], "response.completed")
                    await asyncio.wait_for(cleanup_started.wait(), 3)
                    await ws.send_json({
                        **create, "previous_response_id": first["response"]["id"], "input": "follow up",
                    })
                    with self.assertRaises(TimeoutError):
                        await ws.receive_json(timeout=0.1)
                    self.assertEqual(len(self.seen), 1)
                finally:
                    self.release.set()

                await ws.receive_json(timeout=3)
                second = await ws.receive_json(timeout=3)
                self.assertEqual(second["type"], "response.completed")

        self.assertEqual([a for a, _ in self.seen], ["Bearer upstream-A", "Bearer upstream-B"])
        self.assertEqual(
            [item["role"] for item in self.seen[1][1]["input"]], ["user", "assistant", "user"],
        )

    async def test_export_client_bundle_uses_active_lan_address_and_public_certificate(self):
        root = Path(self.temp.name)
        destination = root / "Forge-Codex-LAN.zip"
        script = Path(__file__).resolve().parents[2] / "resources" / "forge-lan-config.ps1"
        payload = {"destination": str(destination), "script": str(script)}
        with self.assertRaisesRegex(ValueError, "请先开启局域网共享"):
            await self.gateway.command("export_client_bundle", payload)

        await self.gateway.listen(False, "127.0.0.1", 0)
        self.gateway.address = "192.168.10.25"
        self.gateway.lan_port = 19381
        self.assertEqual(await self.gateway.command("export_client_bundle", payload), {"saved": True})
        with ZipFile(destination) as bundle:
            self.assertEqual(set(bundle.namelist()), {
                "Apply-Forge-Gateway.cmd", "Restore-Codex-Settings.cmd", "forge-lan-config.ps1",
                "forge-gateway-ca.pem", "gateway.json",
            })
            self.assertEqual(json.loads(bundle.read("gateway.json")), {"baseUrl": "https://192.168.10.25:19381/v1"})
            self.assertEqual(bundle.read("forge-gateway-ca.pem"), (root / "forge-gateway-ca.pem").read_bytes())
            self.assertIn(b"-Restore", bundle.read("Restore-Codex-Settings.cmd"))
            for name in bundle.namelist():
                self.assertNotIn(self.keys[0]["key"].encode(), bundle.read(name))

    async def test_file_owner_rotation_and_typed_tool_schema(self):
        from aiohttp import FormData

        data = FormData()
        data.add_field("file", b"original bytes", filename="a.txt", content_type="text/plain")
        async with self.client.post(self.base + "/files", headers=self.headers(), data=data) as r:
            rid = (await r.json())["id"]
        payload = {
            "input": [{"role": "user", "content": [{"type": "input_file", "file_id": rid}]}],
            "tools": [
                {
                    "type": "function",
                    "name": "local",
                    "parameters": {"properties": {"file_id": {"type": "string"}}},
                }
            ],
        }
        self.assertEqual((await self.post(payload, 1))[0], 400)
        original = self.keys[0]
        self.keys[0] = self.store.change_key("rotate", {"id": original["id"]})
        self.assertIsNone(self.store.identify(original["key"]))
        self.assertEqual((await self.post(payload))[0], 200)
        self.assertEqual(
            self.seen[0][1]["input"][0]["content"][0]["file_data"],
            "data:text/plain;base64,b3JpZ2luYWwgYnl0ZXM=",
        )
        self.assertEqual(self.seen[0][1]["tools"], payload["tools"])
        self.store.db.execute(
            "UPDATE owners SET expires=? WHERE id=?", (int(time.time()) - 2, original["id"])
        )
        self.assertEqual((await self.post(payload))[0], 401)
        self.store.change_key("revoke", {"id": original["id"]})
        with self.assertRaises(ValueError):
            self.store.get(original["id"], rid)

    async def test_warmup_has_no_upstream_side_effect(self):
        async with self.client.ws_connect(self.base + "/responses", headers=self.headers()) as ws:
            await ws.send_json({"type": "response.create", "generate": False, "input": "original"})
            await ws.receive_json()
            done = await ws.receive_json()
            self.assertFalse(self.seen)
            await ws.send_json(
                {
                    "type": "response.create",
                    "previous_response_id": done["response"]["id"],
                    "input": "additional",
                }
            )
            await ws.receive_json()
            await ws.receive_json()
        self.assertEqual([i["content"] for i in self.seen[0][1]["input"]], ["original", "additional"])

    async def test_ws_retries_full_history_after_checkpoint_storage_fills(self):
        original = {"role": "user", "content": "original"}
        follow = {"role": "user", "content": "follow up"}
        create = {"type": "response.create", "model": "m"}
        async with self.client.ws_connect(self.base + "/responses", headers=self.headers()) as ws:
            with patch("core.gateway_store.OWNER_BUDGET", 0):
                await ws.send_json({**create, "input": [original]})
                item = (await ws.receive_json(timeout=3))["item"]
                done = await ws.receive_json(timeout=3)
                self.assertEqual(done["type"], "response.completed")
                self.assertEqual(
                    self.gateway.status()["records"][0]["result"], "response.completed (续接需完整历史)"
                )

                await ws.send_json({
                    **create, "previous_response_id": done["response"]["id"], "input": [follow],
                })
                error = await ws.receive_json(timeout=3)
                self.assertEqual((error["type"], error["status"]), ("error", 400))
                self.assertEqual(error["error"]["type"], "invalid_request_error")
                self.assertEqual(error["error"]["code"], "previous_response_not_found")
                self.assertEqual(error["error"]["param"], "previous_response_id")
                self.assertEqual(len(self.seen), 1)

                history = [original, {k: v for k, v in item.items() if k != "id"}, follow]
                await ws.send_json({**create, "input": history})
                await ws.receive_json(timeout=3)
                self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.completed")
        self.assertEqual(len(self.seen), 2)
        self.assertEqual(self.seen[1][1]["input"], history)
        self.assertNotIn("previous_response_id", self.seen[1][1])

    async def test_ws_warmup_when_checkpoint_storage_is_full(self):
        async with self.client.ws_connect(self.base + "/responses", headers=self.headers()) as ws:
            with patch("core.gateway_store.OWNER_BUDGET", 0):
                await ws.send_json({"type": "response.create", "generate": False, "input": "original"})
                self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.created")
                done = await ws.receive_json(timeout=3)
                self.assertEqual(done["type"], "response.completed")
                await ws.send_json({
                    "type": "response.create", "previous_response_id": done["response"]["id"],
                    "input": "additional",
                })
                error = await ws.receive_json(timeout=3)
                self.assertEqual(error["error"]["code"], "previous_response_not_found")
        self.assertFalse(self.seen)

    async def test_full_cache_evicts_oldest_response_of_the_same_owner(self):
        owner, other = (key["id"] for key in self.keys)
        snapshot = [{"role": "user", "content": "saved history"}]
        attachment = {"filename": "note.txt", "mime": "text/plain", "base64": "Zm9v"}
        self.store.put(other, "response:oldest", snapshot)
        self.store.put(owner, "file-forge-test", attachment)
        self.store.put(owner, "response:oldest", snapshot)
        self.store.put(owner, "response:recent", snapshot)
        used = self.store.db.execute("SELECT SUM(length(data)) FROM objects WHERE owner=?", (owner,)).fetchone()[0]
        total = self.store.db.execute("SELECT SUM(length(data)) FROM objects").fetchone()[0]

        for limit, budget, evicted, new in (
            ("OWNER_BUDGET", used, "oldest", "new"),
            ("TOTAL_BUDGET", total, "recent", "latest"),
        ):
            with self.subTest(limit=limit), patch(f"core.gateway_store.{limit}", budget):
                self.store.put(owner, f"response:{new}", snapshot)
                with self.assertRaises(ValueError):
                    self.store.get(owner, f"response:{evicted}")
                self.assertEqual(self.store.get(owner, f"response:{new}"), snapshot)
        self.assertEqual(self.store.get(owner, "response:new"), snapshot)
        self.assertEqual(self.store.get(owner, "file-forge-test"), attachment)
        self.assertEqual(self.store.get(other, "response:oldest"), snapshot)

        status, _ = await self.post({"previous_response_id": "latest", "input": "follow up"})
        self.assertEqual(status, 200)
        self.assertEqual(self.seen[-1][1]["input"][:-1], snapshot)

    async def test_full_cache_keeps_old_snapshot_if_replacement_fails(self):
        owner = self.keys[0]["id"]
        snapshot = [{"role": "user", "content": "saved history"}]
        self.store.put(owner, "response:old", snapshot)
        used = self.store.db.execute("SELECT SUM(length(data)) FROM objects").fetchone()[0]

        with patch("core.gateway_store.OWNER_BUDGET", used - 1), self.assertRaises(ValueError):
            self.store.put(owner, "response:new", snapshot)
        self.assertEqual(self.store.get(owner, "response:old"), snapshot)

        self.store.db.execute("""
            CREATE TRIGGER reject_new_snapshot BEFORE INSERT ON objects
            WHEN NEW.id = 'response:new' BEGIN SELECT RAISE(ABORT, 'test write failure'); END
        """)
        with patch("core.gateway_store.OWNER_BUDGET", used), self.assertRaises(sqlite3.IntegrityError):
            self.store.put(owner, "response:new", snapshot)
        self.assertEqual(self.store.get(owner, "response:old"), snapshot)
        with self.assertRaises(ValueError):
            self.store.get(owner, "response:new")

    async def test_responses_finish_with_read_only_cache_database(self):
        self.store.db.execute("PRAGMA query_only=ON")
        with self.assertLogs("core.gateway_protocol", level="WARNING") as logs:
            status, reply = await self.post({"input": "one"})
            self.assertEqual(status, 200)
            self.assertEqual(reply["status"], "completed")
            self.assertEqual(reply["output"][0]["content"][0]["text"], "reply")

            async with self.client.post(
                self.base + "/responses", headers=self.headers(), json={"input": "two", "stream": True},
            ) as stream:
                self.assertEqual(stream.status, 200)
                events = [json.loads(line[6:]) for line in (await stream.text()).splitlines() if line.startswith("data: ")]
                self.assertEqual([event["type"] for event in events], ["response.output_item.done", "response.completed"])

            async with self.client.ws_connect(self.base + "/responses", headers=self.headers()) as ws:
                await ws.send_json({"type": "response.create", "generate": False, "input": "prewarm"})
                self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.created")
                self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.completed")
                await ws.send_json({"type": "response.create", "input": "three"})
                self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.output_item.done")
                self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.completed")
        self.assertEqual(len(self.seen), 3)
        self.assertTrue(all("续接需完整历史" in entry["result"] for entry in self.gateway.proto.records))
        self.assertTrue(any("续接快照写入失败" in line for line in logs.output))
        self.assertTrue(any("请求计数写入失败" in line for line in logs.output))

    async def test_limiter_and_revocation_while_queued(self):
        first = asyncio.create_task(self.post({"model": "hold", "input": "one"}))
        await asyncio.wait_for(self.started.wait(), 3)
        queued = asyncio.create_task(self.post({"input": "never sent"}))
        while not self.gateway.scheduler.waiting:
            await asyncio.sleep(0.01)
        self.assertEqual((await self.post({"input": "other owner"}, 1))[0], 200)
        self.store.change_key("revoke", {"id": self.keys[0]["id"]})
        self.release.set()
        self.assertEqual((await first)[0], 200)
        self.assertIn((await queued)[0], (401, 429))
        self.assertEqual(len(self.seen), 2)
        self.assertEqual(sum(self.gateway.scheduler.active.values()), 0)
        self.assertEqual(self.gateway.scheduler.waiting, 0)

    async def test_weekly_two_percent_checks_after_each_request_before_dispatching_again(self):
        account, other = self.accounts
        account.cap = 4
        account.weekly_remaining = 2
        account.weekly_checked_at = time.time()
        other.enabled = False
        checked = asyncio.Event()
        allow_check = threading.Event()
        loop = asyncio.get_running_loop()
        remaining = iter((2, 1))

        def publish_reading(value):
            account.weekly_remaining = value
            account.weekly_checked_at = time.time()

        def refresh(_account):
            loop.call_soon_threadsafe(checked.set)
            if not allow_check.wait(5):
                raise TimeoutError("test quota reload was not released")
            loop.call_soon_threadsafe(publish_reading, next(remaining))

        with patch("core.gateway.refresh_weekly_quota", side_effect=refresh) as refresh_quota:
            async with self.client.ws_connect(self.base + "/responses", headers=self.headers(1)) as ws:
                first = asyncio.create_task(self.post({"model": "hold", "input": "first"}))
                try:
                    await asyncio.wait_for(self.started.wait(), 3)
                    await ws.send_json({"type": "response.create", "input": "second"})
                    async with asyncio.timeout(3):
                        while not self.gateway.scheduler.waiting:
                            await asyncio.sleep(0.01)
                    publish_reading(3)
                    self.gateway.refreshed = -100.0
                    self.assertEqual(self.gateway.status()["accounts"][0]["reason"], "额度保护中，限单并发")
                    self.release.set()
                    self.assertEqual((await asyncio.wait_for(first, 3))[0], 200)
                    await asyncio.wait_for(checked.wait(), 3)
                    self.assertEqual(len(self.seen), 1)
                    self.assertEqual(self.gateway.status()["accounts"][0]["reason"], "等待复查额度")
                finally:
                    self.release.set()
                    allow_check.set()

                self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.output_item.done")
                self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.completed")
                async with asyncio.timeout(3):
                    while self.gateway.status()["accounts"][0]["reason"] != "周额度剩余 ≤ 1%，已暂停派发":
                        await asyncio.sleep(0.01)
                self.assertEqual(refresh_quota.call_count, 2)
                self.assertEqual([bearer for bearer, _ in self.seen], ["Bearer upstream-A"] * 2)
                await ws.send_json({"type": "response.create", "input": "blocked"})
                event = await ws.receive_json(timeout=3)
                self.assertEqual((event["type"], event["message"]), ("error", "周额度不足，等待账号额度恢复"))

            publish_reading(3)
            self.gateway.refreshed = -100.0
            self.assertEqual((await self.post({"input": "restored"}))[0], 200)
            self.assertEqual(refresh_quota.call_count, 2)

    async def test_weekly_pause_leaves_active_request_running_and_failed_recheck_stays_blocked(self):
        account = self.accounts[0]
        account.cap = 4
        account.weekly_remaining = 3
        account.weekly_checked_at = time.time()
        first = asyncio.create_task(self.post({"model": "hold", "input": "started"}))
        await asyncio.wait_for(self.started.wait(), 3)
        with patch("core.gateway.refresh_weekly_quota", side_effect=TimeoutError):
            account.weekly_remaining = 1
            self.gateway.refreshed = -100.0
            self.assertEqual((await self.post({"input": "fallback"}, 1))[0], 200)
            self.assertEqual(self.seen[-1][0], "Bearer upstream-B")
            self.assertFalse(first.done())
            self.release.set()
            self.assertEqual((await asyncio.wait_for(first, 3))[0], 200)
            await asyncio.gather(*self.gateway.weekly_refreshes)

        account.weekly_remaining = 2
        self.gateway.refreshed = -100.0
        self.assertEqual((await self.post({"input": "old reading"}, 1))[0], 200)
        self.assertEqual(self.seen[-1][0], "Bearer upstream-B")
        pending = self.store.option("weeklyRecheckAfter") or {}
        self.assertGreater(pending[account.quota_key], account.weekly_checked_at)

        await self.gateway.close()
        self.store = GatewayStore(Path(self.temp.name))
        self.gateway = Gateway(self.store, lambda _: self.accounts)
        self.gateway.port = 0
        await self.gateway.restore()
        _, runner = self.gateway.listeners[True]
        self.base = f"https://127.0.0.1:{runner.addresses[0][1]}/v1"
        self.assertEqual((await self.post({"input": "still waiting after restart"}, 1))[0], 200)
        self.assertEqual(self.seen[-1][0], "Bearer upstream-B")

        account.weekly_remaining = 3
        account.weekly_checked_at = time.time()
        self.accounts[1].enabled = False
        self.gateway.refreshed = -100.0
        self.assertEqual((await self.post({"input": "confirmed"}, 1))[0], 200)
        self.assertEqual(self.seen[-1][0], "Bearer upstream-A")
        self.assertEqual(self.store.option("weeklyRecheckAfter"), {})

    async def test_five_hour_quota_rechecks_near_limit_and_pauses_at_one_percent(self):
        account, other = self.accounts
        account.cap = 4
        account.weekly_remaining = 80
        account.five_hour_remaining = 2
        account.weekly_checked_at = account.five_hour_checked_at = time.time()
        self.assertEqual(self.gateway.status()["accounts"][0]["reason"], "5 小时额度保护中，限单并发")

        def publish_reading(remaining):
            account.five_hour_remaining = remaining
            account.weekly_checked_at = account.five_hour_checked_at = time.time()

        loop = asyncio.get_running_loop()

        def refresh_quota(_account):
            loop.call_soon_threadsafe(publish_reading, 1)

        with patch("core.gateway.refresh_weekly_quota", side_effect=refresh_quota) as refresh:
            first = asyncio.create_task(self.post({"model": "hold", "input": "first"}))
            try:
                await asyncio.wait_for(self.started.wait(), 3)
                self.assertEqual((await self.post({"input": "second"}, 1))[0], 200)
                self.assertEqual([bearer for bearer, _ in self.seen], ["Bearer upstream-A", "Bearer upstream-B"])
                other.enabled = False
            finally:
                self.release.set()
            self.assertEqual((await asyncio.wait_for(first, 3))[0], 200)
            async with asyncio.timeout(3):
                while self.gateway.status()["accounts"][0]["reason"] != "5 小时额度剩余 ≤ 1%，已暂停派发":
                    await asyncio.sleep(0.01)
            status, body = await self.post({"input": "blocked"})
            self.assertEqual((status, body["error"]["message"]), (429, "5 小时额度不足，等待账号额度恢复"))
            self.assertEqual(len(self.seen), 2)
            refresh.assert_called_once_with(account)

        publish_reading(100)
        self.gateway.refreshed = -100.0
        self.assertEqual((await self.post({"input": "after reset"}))[0], 200)

    async def test_key_cap_changes_apply_to_queued_turns_on_an_existing_socket(self):
        async def wait_for_queue():
            async with asyncio.timeout(3):
                while not self.gateway.scheduler.waiting:
                    await asyncio.sleep(0.01)

        async def set_cap(cap):
            await self.gateway.command("key", {"action": "set_cap", "id": self.keys[0]["id"], "cap": cap})

        async with self.client.ws_connect(self.base + "/responses", headers=self.headers()) as ws:
            first = asyncio.create_task(self.post({"model": "hold", "input": "one"}))
            try:
                await asyncio.wait_for(self.started.wait(), 3)
                await ws.send_json({"type": "response.create", "input": "wait for higher limit"})
                await wait_for_queue()
                await set_cap("1000")
                self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.output_item.done")
                self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.completed")
                self.assertFalse(first.done())

                await set_cap("1")
                await ws.send_json({"type": "response.create", "input": "wait for unlimited"})
                await wait_for_queue()
                await set_cap(None)
                self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.output_item.done")
                self.assertEqual((await ws.receive_json(timeout=3))["type"], "response.completed")
                self.assertFalse(first.done())
            finally:
                self.release.set()
                self.assertEqual((await asyncio.wait_for(first, 3))[0], 200)

    async def test_key_cap_validation_and_persistence(self):
        existing = self.keys[0]
        huge = "9" * 4500
        await self.gateway.command("key", {"action": "set_cap", "id": existing["id"], "cap": huge})
        for cap in (0, "0", "", "-2", "2.5", "2e6", True):
            with self.subTest(cap=cap), self.assertRaises(ValueError):
                self.store.change_key("set_cap", {"id": existing["id"], "cap": cap})
        unlimited = self.store.change_key("create", {"name": "unlimited", "cap": None})
        large = self.store.change_key("create", {"name": "large", "cap": "0009007199254740993"})

        reopened = GatewayStore(self.store.directory)
        try:
            limits = {row["id"]: row["cap"] for row in reopened.list_keys()}
            self.assertEqual(limits[existing["id"]], huge)
            self.assertIsNone(limits[unlimited["id"]])
            self.assertEqual(limits[large["id"]], "9007199254740993")
            updated = reopened.identify(existing["key"])
            other = reopened.identify(self.keys[1]["key"])
            assert updated is not None and other is not None
            self.assertEqual(updated["cap"], huge)
            self.assertEqual(other["cap"], 1)
        finally:
            reopened.db.close()

    async def test_disable_sharing_drains_inflight_but_keeps_local_listener(self):
        await self.gateway.listen(False, "127.0.0.1", 0)
        _, runner = self.gateway.listeners[False]
        shared = f"https://127.0.0.1:{runner.addresses[0][1]}/v1/responses"
        async with self.client.ws_connect(shared, headers=self.headers(1)) as idle:

            async def hold():
                async with self.client.post(
                    shared, headers=self.headers(), json={"model": "hold", "input": "one"}
                ) as r:
                    return r.status, await r.json()

            running = asyncio.create_task(hold())
            await asyncio.wait_for(self.started.wait(), 3)
            await self.gateway.command("share", {"enabled": False})
            self.release.set()
            self.assertEqual((await running)[0], 200)
            await asyncio.wait_for(idle.receive(), 3)
            self.assertTrue(idle.closed)
            self.assertEqual((await self.post({"input": "still local"}, 1))[0], 200)
        self.assertEqual(len(self.seen), 2)

    async def test_restart_preserves_owners_and_replay_without_resending(self):
        _, first = await self.post({"input": "before restart"})
        await self.gateway.close()
        self.store = GatewayStore(Path(self.temp.name))
        self.gateway = Gateway(self.store, lambda _: self.accounts)
        self.gateway.port = 0
        await self.gateway.restore()
        _, runner = self.gateway.listeners[True]
        self.base = f"https://127.0.0.1:{runner.addresses[0][1]}/v1"
        self.assertEqual(len(self.seen), 1)
        continuation = {"input": "continue", "previous_response_id": first["id"]}
        self.assertEqual((await self.post(continuation, 1))[0], 400)
        self.assertEqual((await self.post(continuation))[0], 200)
        self.assertEqual(len(self.seen), 2)
        self.assertEqual(self.seen[-1][1]["input"][0]["content"], "before restart")
