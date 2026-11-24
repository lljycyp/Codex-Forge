import asyncio
import json
import ssl
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from aiohttp import ClientSession, TCPConnector, web
from aiohttp.test_utils import TestServer
from core.gateway import Gateway
from core.gateway_accounts import Account, configure_api
from core.gateway_continuation import quota_limit
from core.gateway_protocol import sse_events
from core.gateway_store import GatewayStore


def message_events(rid, chunks, *, error=None, reasoning=False, snapshot_only=False):
    message = {
        "id": "msg_" + rid,
        "type": "message",
        "role": "assistant",
        "content": [],
        "status": "in_progress",
    }
    response = {"id": rid, "object": "response", "model": "m", "status": "in_progress", "output": []}
    events = [{"type": "response.created", "response": response}]
    idx = int(reasoning)
    if reasoning:
        reason = {"type": "reasoning", "id": "rs_" + rid, "summary": [], "encrypted_content": "mock"}
        events.extend(
            {"type": "response.output_item." + when, "output_index": 0, "item": reason}
            for when in ("added", "done")
        )
    pos = {"output_index": idx, "item_id": message["id"], "content_index": 0}
    events.extend(
        [
            {"type": "response.output_item.added", "output_index": idx, "item": message},
            {"type": "response.content_part.added", **pos, "part": {"type": "output_text", "text": ""}},
        ]
    )
    events.extend({"type": "response.output_text.delta", **pos, "delta": chunk} for chunk in chunks)
    if error:
        events.append(
            {"type": "response.failed", "response": {**response, "status": "failed", "error": error}}
        )
    else:
        text = "".join(chunks)
        part = {"type": "output_text", "text": text, "annotations": []}
        item = {**message, "status": "completed", "content": [part]}
        if not snapshot_only:
            events.extend(
                [
                    {"type": "response.output_text.done", **pos, "text": text},
                    {"type": "response.content_part.done", **pos, "part": part},
                    {"type": "response.output_item.done", "output_index": idx, "item": item},
                ]
            )
        events.append(
            {
                "type": "response.completed",
                "response": {
                    **response,
                    "status": "completed",
                    "output": ([reason] if reasoning else []) + [item],
                },
            }
        )
    return [{**event, "sequence_number": i} for i, event in enumerate(events)]


class ContinuationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.calls = []
        self.script = []

        def next_reply(request, payload):
            self.calls.append((request.headers["Authorization"], payload, time.monotonic()))
            return self.script.pop(0)

        async def http(request):
            reply = next_reply(request, await request.json())
            if isinstance(reply, tuple):
                status, body, headers = reply
                return web.json_response(body, status=status, headers=headers)
            return web.Response(
                content_type="text/event-stream",
                body=b"".join(b"data: " + json.dumps(e).encode() + b"\n\n" for e in reply),
            )

        async def ws(request):
            socket = web.WebSocketResponse()
            await socket.prepare(request)
            for event in next_reply(request, await socket.receive_json()):
                await socket.send_json(event)
            await socket.close()
            return socket

        app = web.Application()
        app.router.add_post("/responses", http)
        app.router.add_get("/responses", ws)
        self.origin = TestServer(app)
        await self.origin.start_server()
        self.addAsyncCleanup(self.origin.close)
        base = str(self.origin.make_url("")).rstrip("/")
        self.accounts = [
            Account(k, k, 1, True, base=base, headers={"Authorization": k}, identity=k) for k in ("A", "B")
        ]
        self.store = GatewayStore(Path(self.temp.name))
        self.gateway = Gateway(self.store, lambda _: self.accounts)
        self.gateway.port = 0
        await self.gateway.start()
        self.addAsyncCleanup(self.gateway.close)
        self.key = self.store.change_key("create", {"name": "one", "cap": 1})
        ctx = ssl.create_default_context(cafile=str(Path(self.temp.name) / "forge-gateway-ca.pem"))
        self.client = ClientSession(
            connector=TCPConnector(ssl=ctx), headers={"Authorization": "Bearer " + self.key["key"]}
        )
        self.addAsyncCleanup(self.client.close)
        self.url = f"https://127.0.0.1:{self.gateway.listeners[True][1].addresses[0][1]}/v1/responses"

    async def collect(self, body, websocket=False):
        async with asyncio.timeout(8):
            if websocket:
                async with self.client.ws_connect(self.url) as ws:
                    await ws.send_json({"type": "response.create", **body})
                    events = []
                    while True:
                        event = await ws.receive_json()
                        events.append(event)
                        if event["type"] in ("response.completed", "response.failed", "error"):
                            return events
            async with self.client.post(self.url, json={**body, "stream": True}) as response:
                return [event async for event in sse_events(response)]

    async def verify_join(self, websocket):
        prefix = "窗边的灯光是蓝色"
        self.script = [
            message_events(
                "first",
                [prefix],
                error={"type": "usage_limit_reached", "resets_in_seconds": 1},
                reasoning=True,
            ),
            message_events("second", ["灯光", "是蓝色", "的。"], reasoning=True, snapshot_only=not websocket),
        ]
        self.store.put(
            self.key["id"], "response:previous", [{"role": "assistant", "content": "saved history"}]
        )
        events = await self.collect(
            {"model": "m", "previous_response_id": "previous", "input": "original question"}, websocket
        )
        expected = prefix + "的。"
        self.assertEqual([a for a, _, _ in self.calls], ["A", "A"])
        self.assertGreaterEqual(self.calls[1][2] - self.calls[0][2], 0.99)
        resume = self.calls[1][1]["input"]
        self.assertEqual([i.get("content") for i in resume[:2]], ["saved history", "original question"])
        self.assertEqual(resume[-2], {"role": "assistant", "content": prefix})
        self.assertTrue(any(e["type"] == "response.in_progress" for e in events))
        self.assertEqual(sum(e["type"] == "response.created" for e in events), 1)
        self.assertEqual(sum(e["type"] == "response.output_text.done" for e in events), 1)
        seq = [e["sequence_number"] for e in events]
        self.assertEqual(seq, sorted(set(seq)))
        deltas = [e for e in events if e["type"] == "response.output_text.delta"]
        self.assertEqual("".join(e["delta"] for e in deltas), expected)
        self.assertEqual({(e["item_id"], e["output_index"]) for e in deltas}, {("msg_first", 1)})
        self.assertEqual(events[-1]["type"], "response.completed")
        result = events[-1]["response"]
        self.assertEqual(result["id"], "first")
        self.assertEqual([i["type"] for i in result["output"]], ["reasoning", "message"])
        self.assertEqual(result["output"][1]["content"][0]["text"], expected)
        cached = self.store.get(self.key["id"], "response:first")
        self.assertEqual(len(cached), 4)
        self.assertEqual(cached[-1]["content"][0]["text"], expected)
        self.assertFalse(self.gateway.proto.quota_waiting)

    async def test_native_websocket_keeps_response_and_message_identity(self):
        await self.verify_join(True)

    async def test_sse_handles_terminal_snapshot_without_done_frames(self):
        await self.verify_join(False)

    async def test_confirmed_quota_reset_resumes_waiting_turn_and_new_dispatch(self):
        account = self.accounts[0]
        account.cap = 2
        account.weekly_remaining = 2
        self.accounts[1].enabled = False
        self.script = [
            message_events("original", ["before "], error={"type": "usage_limit_reached", "resets_in_seconds": 3600}),
            message_events("continued", ["after"]),
            message_events("new", ["available"]),
        ]
        with patch("core.gateway_protocol.CHATGPT_BASE", account.base):
            async with self.client.ws_connect(self.url) as ws, asyncio.timeout(5):
                await ws.send_json({"type": "response.create", "input": "start"})
                while (await ws.receive_json())["type"] != "response.in_progress":
                    pass
                self.assertFalse(self.gateway.scheduler.eligible(account))
                self.assertIn(account.quota_key, self.gateway.scheduler.weekly_recheck_after)
                exhausted = replace(account, weekly_remaining=0, reason="当前额度已用完", quota_reset=time.time() + 3600)
                self.accounts = [exhausted, self.accounts[1]]
                self.gateway.refreshed = -100.0
                self.assertIs(self.gateway.accounts()[0], exhausted)
                restored = replace(account, weekly_remaining=100, weekly_checked_at=time.time())
                self.accounts = [restored, self.accounts[1]]
                await self.gateway.command("quota_reset", {
                    "profileId": account.id, "scope": account.identity, "restoredAt": time.monotonic(),
                })
                self.assertIs(self.gateway.accounts()[0], restored)
                other_owner = {"id": "another-owner", "cap": 1}
                async with asyncio.timeout(0.5):
                    async with self.gateway.scheduler.reserve(other_owner, lambda: other_owner) as selected:
                        self.assertIs(selected, restored)
                while (event := await ws.receive_json())["type"] != "response.completed":
                    pass
            new_turn = await self.collect({"input": "another request"})
        self.assertEqual(event["response"]["id"], "original")
        self.assertEqual(new_turn[-1]["response"]["id"], "new")
        self.assertEqual([auth for auth, _, _ in self.calls], ["A", "A", "A"])

    async def test_quota_reset_preserves_other_failures_and_new_quota_errors(self):
        first, second = self.accounts
        scheduler = self.gateway.scheduler
        before = time.monotonic() - 2
        scheduler.rejected(first.id, 401, 60)
        self.gateway.proto.record_limit(first, "rate_limit_exceeded", 120, before)
        generic_until = scheduler.cooldown_until(first)
        scheduler.quota_rejected(first, 3600, before)
        scheduler.quota_rejected(second, 3600, before)
        scheduler.quota_rejected(first, 10, before + 2)

        await self.gateway.command("quota_reset", {
            "profileId": first.id, "scope": "previous_login", "restoredAt": before + 1,
        })
        self.assertGreater(scheduler.cooldown_until(first), generic_until)
        await self.gateway.command("quota_reset", {
            "profileId": first.id, "scope": first.identity, "restoredAt": before + 1,
        })
        scheduler.quota_rejected(first, 3600, before)
        self.assertEqual(scheduler.cooldown_until(first), generic_until)
        self.assertGreater(scheduler.cooldown_until(second), generic_until)
        scheduler.cooldown.pop(first.id)
        self.assertFalse(scheduler.eligible(first))

    async def test_cancel_while_waiting_never_starts_another_request(self):
        self.script = [
            message_events("r", ["partial"], error={"code": "usage_limit_reached", "resets_in_seconds": 3600})
        ]
        async with self.client.ws_connect(self.url) as ws:
            await ws.send_json({"type": "response.create", "input": "go"})
            async with asyncio.timeout(4):
                while (await ws.receive_json())["type"] != "response.in_progress":
                    pass
                await ws.send_json({"type": "response.cancel"})
                self.assertEqual((await ws.receive_json())["type"], "response.cancelled")
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.gateway.proto.quota_waiting)
        self.assertEqual(sum(self.gateway.scheduler.active.values()), 0)

    async def test_tool_call_is_never_replayed(self):
        self.script = [
            [
                {
                    "type": "response.output_item.added",
                    "item": {"type": "function_call", "name": "save", "call_id": "id"},
                },
                {"type": "error", "error": {"code": "usage_limit_reached", "resets_in_seconds": 1}},
            ]
        ]
        events = await self.collect({"input": "save"})
        self.assertEqual(events[-1]["type"], "error")
        self.assertEqual(len(self.calls), 1)

    async def test_pending_request_stops_after_key_revocation(self):
        self.script = [
            message_events("r", ["partial"], error={"code": "usage_limit_reached", "resets_in_seconds": 600})
        ]
        async with self.client.ws_connect(self.url) as ws:
            await ws.send_json({"type": "response.create", "input": "go"})
            async with asyncio.timeout(5):
                while (await ws.receive_json())["type"] != "response.in_progress":
                    pass
                self.store.change_key("revoke", {"id": self.key["id"]})
                event = await ws.receive_json()
                self.assertEqual((event["type"], event["code"]), ("error", "continuation_stopped"))
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.gateway.proto.quota_waiting)

    async def test_two_interruptions_use_merged_prefix_and_count_one_request(self):
        limit = {"type": "usage_limit_reached", "resets_in_seconds": 1}
        self.script = [
            message_events("one", ["原来的蓝色"], error=limit),
            message_events("two", ["蓝色", "和红色"], error=limit),
            message_events("three", ["原来的蓝", "色和红色", "都在。"]),
        ]
        events = await self.collect({"input": "colors"})
        self.assertEqual([a for a, _, _ in self.calls], ["A", "A", "A"])
        self.assertEqual(self.calls[2][1]["input"][-2]["content"], "原来的蓝色和红色")
        self.assertEqual(
            "".join(e["delta"] for e in events if e["type"] == "response.output_text.delta"),
            "原来的蓝色和红色都在。",
        )
        self.assertEqual(self.store.list_keys()[0]["calls"], 1)
        self.assertEqual(events[-1]["response"]["id"], "one")

    async def test_new_seat_under_same_profile_never_receives_old_context(self):
        self.script = [
            message_events("r", ["private"], error={"code": "usage_limit_reached", "resets_in_seconds": 30})
        ]
        async with self.client.ws_connect(self.url) as ws:
            await ws.send_json({"type": "response.create", "input": "go"})
            async with asyncio.timeout(5):
                while (await ws.receive_json())["type"] != "response.in_progress":
                    pass
                self.accounts[0] = Account(
                    "A", "A", 1, True, base=self.accounts[0].base, identity="other-seat"
                )
                event = await ws.receive_json()
                self.assertEqual(event["code"], "continuation_stopped")
        self.assertEqual(len(self.calls), 1)

    async def test_explicit_output_budget_spans_both_attempts(self):
        first = message_events(
            "first", ["half"], error={"code": "usage_limit_reached", "resets_in_seconds": 1}
        )
        first[-1]["response"]["usage"] = {"input_tokens": 10, "output_tokens": 3, "total_tokens": 13}
        last = message_events("next", [" done"])
        last[-1]["response"]["usage"] = {"input_tokens": 20, "output_tokens": 4, "total_tokens": 24}
        self.script = [first, last]
        events = await self.collect({"input": "go", "max_output_tokens": 12})
        self.assertEqual(self.calls[1][1]["max_output_tokens"], 9)
        self.assertEqual(
            events[-1]["response"]["usage"], {"input_tokens": 30, "output_tokens": 7, "total_tokens": 37}
        )

    async def test_irrecoverable_quota_does_not_schedule_or_switch(self):
        self.script = [(429, {"error": {"code": "insufficient_quota"}}, {})]
        async with self.client.post(self.url, json={"input": "go"}) as response:
            self.assertEqual(response.status, 429)
        self.assertEqual(len(self.calls), 1)
        self.assertFalse(self.gateway.proto.quota_waiting)

    async def test_deployment_quota_uses_only_same_resource_and_credential(self):
        self.accounts[0].deployment, self.accounts[0].spillover = "main", "backup"
        self.script = [
            message_events(
                "one",
                ["hello "],
                error={"code": "rate_limit_exceeded", "scope": "deployment", "resets_in_seconds": 120},
            ),
            message_events("two", ["world"]),
        ]
        async with asyncio.timeout(5):
            async with self.client.post(self.url, json={"model": "main", "input": "go"}) as response:
                result = await response.json()
        self.assertEqual(result["id"], "one")
        self.assertEqual(result["output"][0]["content"][0]["text"], "hello world")
        self.assertEqual([(a, p["model"]) for a, p, _ in self.calls], [("A", "main"), ("A", "backup")])

    async def test_shared_limit_waits_even_with_backup(self):
        self.accounts[0].deployment, self.accounts[0].spillover = "main", "backup"
        self.script = [
            (429, {"error": {"type": "rate_limit_exceeded", "scope": "organization"}}, {"Retry-After": "1"}),
            message_events("ok", ["done"]),
        ]
        async with asyncio.timeout(5):
            async with self.client.post(self.url, json={"model": "main", "input": "go"}) as response:
                result = await response.json()
        self.assertEqual(result["output"][0]["content"][0]["text"], "done")
        self.assertEqual([(a, p["model"]) for a, p, _ in self.calls], [("A", "main"), ("A", "main")])
        self.assertGreaterEqual(self.calls[1][2] - self.calls[0][2], 0.99)


class QuotaSignals(unittest.TestCase):
    def test_authorized_azure_resource_is_read_from_profile(self):
        account = Account("A", "A", 2, True)
        conf = {
            "model_provider": "team",
            "model": "primary",
            "model_providers": {
                "team": {
                    "base_url": "https://example.openai.azure.com/openai/v1/",
                    "http_headers": {"x-ms-spillover-deployment": "secondary"},
                }
            },
        }
        configure_api(account, conf)
        self.assertEqual((account.deployment, account.spillover), ("primary", "secondary"))
        conf["model_providers"]["team"]["base_url"] = "https://example.openai.azure.com.invalid/openai/v1"
        with self.assertRaises(ValueError):
            configure_api(account, conf)

    def test_retry_after_and_shared_scope(self):
        limited = quota_limit({"type": "usage_limit_reached"}, {"retry-after-ms": "2000"})
        assert limited is not None
        self.assertEqual(limited.delay, 2)
        self.assertIsNone(quota_limit({"code": "account_deactivated"}, status=403))
        shared = quota_limit(
            {"code": "rate_limit_exceeded", "scope": "workspace"},
            {"x-ratelimit-remaining-tokens": "0", "x-ratelimit-limit-tokens": "5"},
        )
        assert shared is not None
        self.assertFalse(shared.deployment_limited)
