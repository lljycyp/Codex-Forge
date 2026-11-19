import asyncio
import json
import ssl
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from aiohttp import ClientSession, TCPConnector, web
from aiohttp.test_utils import TestServer
from core.gateway import Gateway
from core.gateway_accounts import Account
from core.gateway_launch import OVERRIDE, prepare_launch
from core.gateway_store import GatewayStore


class GatewayDesktopLaunch(unittest.TestCase):
    def test_running_client_refused_before_touching_home_or_starting_gateway(self):
        with (
            patch("bridge.commands.load_config", return_value={"launch_mode": "switch", "codex_skin_enabled": True}),
            patch("bridge.commands._running_codex_count", return_value=1),
            patch("bridge.commands._resolve_codex_app_source_path") as resolve,
            patch("bridge.commands._stop_running_codex_processes") as stop,
        ):
            with self.assertRaisesRegex(ValueError, "Codex 正在运行"):
                prepare_launch("https://localhost/v1", "ca.pem")
            resolve.assert_not_called()
            stop.assert_not_called()

    def test_skin_uses_original_home_and_only_the_new_process(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "auth.json").write_text("{}", encoding="utf-8")
            (root / "resources").mkdir()
            (root / "resources" / "app.asar").write_bytes(OVERRIDE.encode())
            with (
                patch.dict("os.environ", {"CODEX_HOME": temp}),
                patch("bridge.commands.load_config", return_value={"launch_mode": "switch", "codex_skin_enabled": True}),
                patch("bridge.commands._running_codex_count", return_value=0),
                patch("bridge.commands._resolve_codex_app_source_path", return_value=root / "Codex.exe"),
                patch("bridge.commands._allocate_codex_skin_port", return_value=19335),
                patch("core.gateway_launch.resolve_codex_execution_path", return_value=root / "Codex.exe"),
                patch("core.gateway_launch.subprocess.Popen") as spawn,
            ):
                spawn.return_value.pid = 789
                plan = prepare_launch("https://127.0.0.1:19380/v1", root / "ca.pem")
                self.assertEqual(plan.env["CODEX_HOME"], temp)
                self.assertEqual(plan.env[OVERRIDE], "https://127.0.0.1:19380/v1")
                self.assertIn("--remote-debugging-address=127.0.0.1", plan.command)
                self.assertIn("--remote-debugging-port=19335", plan.command)
                self.assertEqual(
                    plan.start()["skinSession"], {"profileName": "__system__", "port": 19335, "processId": 789}
                )


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
        self.client = ClientSession(connector=TCPConnector(ssl=ctx))

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
