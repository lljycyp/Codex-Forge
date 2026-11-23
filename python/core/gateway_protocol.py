import asyncio
import base64
import contextlib
import json
import mimetypes
import secrets
import sqlite3
import time
import uuid
from collections import Counter, deque
from collections.abc import AsyncGenerator, Callable
from pathlib import PurePath

import aiohttp
from aiohttp import WSMsgType, web

from core.gateway_accounts import CHATGPT_BASE, CapacityError
from core.gateway_continuation import (
    AnswerStream,
    Attempt,
    ProtocolError,
    QuotaLimit,
    add_usage,
    quota_limit,
    replay_item,
)
from core.gateway_store import MAX_RESOURCE
from core.logger import get_logger

logger = get_logger(__name__)
OWNER = web.RequestKey[dict]("gateway_owner")
AUTH = web.RequestKey[Callable[[], dict | None]]("gateway_auth")
LISTENING = web.RequestKey[Callable[[], bool]]("gateway_listening")
MAX_BODY = 16 * 1024 * 1024
MAX_WS_CONNECTIONS = 64
MAX_WS_CONNECTIONS_PER_KEY = 12
TERMINAL = {"response.completed", "response.failed", "response.incomplete", "response.cancelled", "error"}


def error_body(message, code):
    return {"error": {"message": str(message), "type": "gateway_error", "code": code}}


def as_items(value):
    if isinstance(value, str):
        return [{"role": "user", "content": value}]
    if not isinstance(value, list):
        raise ProtocolError("input 应为字符串或数组")
    return value


def prepare_input(store, owner, body):
    if not isinstance(body, dict):
        raise ProtocolError("请求必须为 JSON 对象")
    body = dict(body)
    if "model" in body and (not isinstance(body["model"], str) or len(body["model"]) > 200):
        raise ValueError("无效的模型名称")
    if body.get("background"):
        raise ValueError("此网关只支持前台生成")
    if body.get("conversation"):
        raise ValueError("请使用网关返回的 previous_response_id 或传入完整历史")
    items = as_items(body.get("input", []))
    previous = body.pop("previous_response_id", None)
    if previous:
        try:
            history = store.get(owner, "response:" + str(previous))
        except ValueError as exc:
            raise ProtocolError(
                "续接状态不存在，请使用完整历史重新连接", 400, "previous_response_not_found"
            ) from exc
        items = history + items
    body["input"] = items

    # Never resolve opaque upstream resource IDs using another caller's upstream credentials.
    def expand(node):
        if isinstance(node, list):
            return [expand(item) for item in node]
        if not isinstance(node, dict):
            return node
        if node.get("type") == "item_reference" or any(
            k in node
            for k in (
                "vector_store_ids",
                "container_id",
                "uploaded_file_id",
                "file_ids",
                "container",
                "connector_id",
            )
        ):
            raise ValueError("该服务端资源不能在账号间重建，请提供完整内容")
        if "file_id" in node:
            rid = node["file_id"]
            if not isinstance(rid, str) or not rid.startswith("file-forge-"):
                raise ValueError("请先通过此 Key 向 Forge 上传文件")
            data = store.get(owner, rid)
            link = "data:" + data["mime"] + ";base64," + data["base64"]
            replacement = {k: v for k, v in node.items() if k != "file_id"}
            if node.get("type") == "input_image" and data["mime"].startswith("image/"):
                return {**replacement, "image_url": link}
            if node.get("type") == "input_file":
                return {**replacement, "filename": data["filename"], "file_data": link}
            raise ValueError("该输入不支持内联文件")
        return {**node, "content": expand(node["content"])} if isinstance(node.get("content"), list) else node

    # Keep the compact local file handles in checkpoints, expanding bytes only on the wire.
    wire = {**body, "input": expand(items)}
    if body.get("prompt") or any(
        tool.get("type") in ("file_search", "mcp")
        or (tool.get("type") == "code_interpreter" and tool.get("container") != "auto")
        for tool in body.get("tools") or []
        if isinstance(tool, dict)
    ):
        raise ValueError("此服务端资源未在网关登记，不能由共享账号读取")
    if wire.get("prompt_cache_key"):
        wire["prompt_cache_key"] = str(
            uuid.uuid5(uuid.NAMESPACE_URL, owner + "/" + str(wire["prompt_cache_key"]))
        )
    return items, wire


async def sse_events(response):
    lines, size = [], 0
    pending = bytearray()
    async for block in response.content.iter_chunked(64 * 1024):
        pending.extend(block)
        while (pos := pending.find(b"\n")) >= 0:
            line = bytes(pending[:pos]).rstrip(b"\r")
            del pending[: pos + 1]
            if line.startswith(b"data:"):
                data = line[5:].lstrip(b" ")
                size += len(data)
                if size > MAX_RESOURCE:
                    raise ProtocolError("上游事件过大", 502)
                lines.append(data)
            elif not line and lines:
                data = b"\n".join(lines)
                lines, size = [], 0
                if data != b"[DONE]":
                    yield json.loads(data)
        if len(pending) > MAX_RESOURCE:
            raise ProtocolError("上游事件过大", 502)
    if lines or pending.strip():
        raise ProtocolError("上游事件流意外结束", 502)


class Protocol:
    def __init__(self, store, scheduler, client, identify, local):
        self.store, self.scheduler, self.client = store, scheduler, client
        self.identify, self.local = identify, local
        self.records = deque(maxlen=100)
        self.sockets = {}
        self.pending_handshakes = {}
        self.last_ws_rejection = None
        self.generating = set()
        self.uploads = 0
        self.quota_waiting = {}

    def websocket_counts(self):
        counts = Counter(self.pending_handshakes.values())
        counts.update(owner for owner, _ in self.sockets.values())
        return counts

    def app(self, local, accepting):
        @web.middleware
        async def guard(request, handler):
            try:
                if not self.scheduler.accepting or not accepting():
                    raise ProtocolError("服务正在停止", 503)
                scheme, _, key = request.headers.get("Authorization", "").partition(" ")
                if scheme.lower() != "bearer":
                    raise ProtocolError("需要 Bearer 凭证", 401)
                if not key or len(key) > 32000:
                    raise ProtocolError("缺少有效凭证", 401)

                def auth():
                    if not accepting():
                        return None
                    return self.identify(key) or (self.local(key) if local else None)

                if not (owner := auth()):
                    raise ProtocolError("凭证无效或已被停用", 401)
                request[OWNER], request[AUTH], request[LISTENING] = owner, auth, accepting
                return await handler(request)
            except ProtocolError as exc:
                return web.json_response(error_body(exc, exc.code), status=exc.status)
            except CapacityError as exc:
                return web.json_response(error_body(exc, "capacity"), status=429)
            except (TypeError, ValueError, KeyError) as exc:
                return web.json_response(error_body(exc, "invalid_request_error"), status=400)
            except (aiohttp.ClientError, TimeoutError, OSError):
                return web.json_response(error_body("上游连接失败", "upstream_error"), status=502)

        app = web.Application(middlewares=[guard], client_max_size=MAX_BODY)
        app.router.add_get("/v1/responses", self.websocket, allow_head=False)
        app.router.add_post("/v1/responses", self.responses)
        app.router.add_post("/v1/responses/compact", self.compact)
        app.router.add_get("/v1/models", self.models, allow_head=False)
        app.router.add_post("/v1/files", self.upload)
        return app

    async def upload(self, request):
        if self.uploads >= 4:
            raise CapacityError("正在上传的文件过多")
        self.uploads += 1
        try:
            form = await request.post()
            file = form.get("file")
            if not isinstance(file, web.FileField):
                raise ProtocolError("请选择文件")
            content = file.file.read(MAX_BODY + 1)
            if len(content) > MAX_BODY:
                raise ValueError("文件超过 16 MiB")
            name = PurePath(file.filename).name
            mime = str(file.content_type or mimetypes.guess_type(name)[0] or "application/octet-stream")
            rid = "file-forge-" + secrets.token_hex(16)
            if not request[AUTH]():
                raise ProtocolError("凭证已失效", 401)
            self.store.put(
                request[OWNER]["id"],
                rid,
                {"filename": name, "mime": mime, "base64": base64.b64encode(content).decode()},
            )
            return web.json_response(
                {
                    "object": "file",
                    "id": rid,
                    "bytes": len(content),
                    "filename": name,
                    "purpose": str(form.get("purpose") or "user_data"),
                    "created_at": int(time.time()),
                }
            )
        finally:
            self.uploads -= 1

    def headers(self, account, request):
        hdr = {"User-Agent": "Codex-Forge/1 Responses", "originator": "codex_cli_rs", **account.headers}
        for key in ("version", "OpenAI-Beta"):
            if request.headers.get(key):
                hdr[key] = request.headers[key]
        for key in ("session_id", "thread_id"):
            if request.headers.get(key):
                hdr[key] = str(
                    uuid.uuid5(uuid.NAMESPACE_URL, request[OWNER]["id"] + "/" + request.headers[key])
                )
        return hdr

    async def check(self, response, account):
        if response.status < 300:
            return
        wait = response.headers.get("Retry-After", "")
        # Provider diagnostics can contain account identifiers; expose the protocol code, never credentials.
        code = "upstream_error"
        try:
            info = json.loads(await response.content.read(8192))
            error = info.get("error") or {}
            limit = quota_limit(error, response.headers, response.status)
            if limit:
                self.scheduler.rejected(account.id, 429, limit.delay if limit.delay is not None else 60)
                raise limit
            value = error.get("code") or error.get("type")
            if isinstance(value, str) and value.replace("_", "").isalnum() and len(value) <= 64:
                code = value
        except QuotaLimit:
            raise
        except (ValueError, AttributeError):
            pass
        self.scheduler.rejected(account.id, response.status, int(wait) if wait.isdigit() else 60)
        raise ProtocolError(
            f"上游返回 HTTP {response.status}（{code}）",
            response.status if response.status >= 400 else 502,
            code,
        )

    async def models(self, request):
        async with (
            self.scheduler.reserve(request[OWNER], request[AUTH]) as account,
            self.client.get(
                account.base + "/models",
                headers=self.headers(account, request),
                params={"client_version": request.query.get("client_version", "0.169.0")}
                if account.base == CHATGPT_BASE
                else {},
                allow_redirects=False,
            ) as resp,
        ):
            await self.check(resp, account)
            return web.Response(body=await resp.read(), content_type="application/json")

    async def compact(self, request):
        body = await request.json()
        owner = request[OWNER]["id"]
        _, wire = prepare_input(self.store, owner, body)
        async with self.scheduler.reserve(request[OWNER], request[AUTH], wire.get("model")) as account:
            if account.base == CHATGPT_BASE:
                # Codex subscriptions expose remote compaction as a Responses generation.
                headers = self.headers(account, request)
                betas = [v.strip() for v in headers.get("OpenAI-Beta", "").split(",") if v.strip()]
                if "remote_compaction_v2" not in betas:
                    betas.append("remote_compaction_v2")
                headers["OpenAI-Beta"] = ",".join(betas)
                payload = {**wire, "input": [*wire["input"], {"type": "compaction_trigger"}]}
                output = []
                async for event in self.upstream(account, headers, payload, False):
                    if event.get("type") == "response.output_item.done":
                        output.append(event["item"])
                    if event.get("type") == "response.completed":
                        response = event["response"]
                        output = response.get("output") or output
                        if not any(
                            i.get("type") == "compaction" and i.get("encrypted_content") for i in output
                        ):
                            break
                        return web.json_response(
                            {
                                "id": response["id"],
                                "object": "response.compaction",
                                "created_at": response.get("created_at", int(time.time())),
                                "output": output,
                                "usage": response.get("usage"),
                            }
                        )
                raise ProtocolError("上游未返回可续用的加密压缩块", 502)
            async with self.client.post(
                account.base + "/responses/compact",
                json=wire,
                headers=self.headers(account, request),
                allow_redirects=False,
            ) as resp:
                await self.check(resp, account)
                value = await resp.json(content_type=None)
                if not isinstance(value.get("output"), list):
                    raise ProtocolError("上游未返回压缩结果", 502)
                return web.json_response(value)

    async def answer_events(self, account, request, wire, websocket) -> AsyncGenerator[dict, None]:
        state = AnswerStream(wire)
        payload = wire
        original_identity = (account.id, account.identity, account.base, account.deployment)
        backup = ""
        backoff = 60
        token_budget = wire.get("max_output_tokens")
        prior_usage = {}
        while True:
            adapter = Attempt(state)
            failure = {}
            try:
                stream = self.upstream(account, self.headers(account, request), payload, websocket)
                async with contextlib.aclosing(stream):
                    async for event in stream:
                        kind = event.get("type")
                        if kind == "response.completed" and prior_usage and event["response"].get("usage"):
                            response = event["response"]
                            event = {
                                **event,
                                "response": {**response, "usage": add_usage(prior_usage, response["usage"])},
                            }
                        if kind in ("response.failed", "response.incomplete", "error"):
                            resp = event.get("response") or {}
                            error = (
                                resp.get("error")
                                or event.get("error")
                                or resp.get("incomplete_details")
                                or event
                            )
                            limit = quota_limit(error, event.get("headers"), event.get("status"))
                            if limit:
                                failure = event
                                raise limit
                        for mapped in adapter.translate(event):
                            for output in state.publish(mapped):
                                yield output
                        if kind in TERMINAL:
                            return
                raise ProtocolError("上游在生成结束前断开", 502)
            except QuotaLimit as limit:
                delay = max(1, limit.delay if limit.delay is not None else backoff)
                backoff = min(900, backoff * 2)
                self.scheduler.rejected(account.id, 429, delay)
                usage = (failure.get("response") or {}).get("usage") or {}
                prior_usage = add_usage(prior_usage, usage)
                if isinstance(token_budget, int) and (state.open or state.done or failure):
                    spent = usage.get("output_tokens")
                    # Resetting an explicit per-response limit could exceed the caller's budget.
                    token_budget = token_budget - spent if type(spent) is int and spent >= 0 else 0
                if not state.can_resume(failure) or (isinstance(token_budget, int) and token_budget <= 0):
                    if failure:
                        for mapped in adapter.translate(failure):
                            for output in state.publish(mapped):
                                yield output
                        return
                    for output in state.flush():
                        yield output
                    raise
                use_backup = (
                    account.spillover
                    if (not backup and limit.deployment_limited and wire.get("model") == account.deployment)
                    else ""
                )
            except (ProtocolError, aiohttp.ClientError, TimeoutError, OSError):
                for output in state.flush():
                    yield output
                raise
            # A client keeps the same response ID and sees a single terminal event.
            state.resuming = True
            state.closers.clear()
            if not state.response.get("id"):
                created = {
                    "id": "resp_forge_" + secrets.token_hex(16),
                    "object": "response",
                    "created_at": int(time.time()),
                    "model": state.model,
                    "status": "in_progress",
                    "output": [],
                }
                yield state.deliver({"type": "response.created", "response": created})
            payload = state.continuing_input(wire)
            if token_budget is not None:
                payload = {**payload, "max_output_tokens": token_budget}
            now = time.monotonic()
            earliest = now if use_backup else now + delay
            heartbeat = now
            # A verified loopback request survives local token refresh. New turns still authenticate normally.
            authorized = request[LISTENING] if request[OWNER]["id"] == "local" else request[AUTH]
            self.quota_waiting[state] = account.id
            try:
                while True:
                    if not self.scheduler.accepting or not authorized():
                        raise ProtocolError(
                            "网关已停止或访问 Key 已失效，续写已停止", 403, "continuation_stopped"
                        )
                    current = next((a for a in self.scheduler.accounts() if a.id == account.id), None)
                    if (
                        not current
                        or not current.enabled
                        or (current.id, current.identity, current.base, current.deployment)
                        != original_identity
                    ):
                        raise ProtocolError(
                            "原账号已停用或身份已变更，续写已停止", 409, "continuation_stopped"
                        )
                    if current.reason and not (current.quota_reset or current.token_expired):
                        raise ProtocolError(
                            "原账号当前不可用：" + current.reason, 409, "continuation_stopped"
                        )
                    until = max(earliest, time.monotonic() + current.quota_reset - time.time())
                    if not use_backup:
                        until = max(until, self.scheduler.cooldown.get(account.id, 0))
                    now = time.monotonic()
                    if now >= until and not current.reason:
                        account = current
                        break
                    if now >= heartbeat:
                        yield state.deliver({"type": "response.in_progress", "response": state.response})
                        heartbeat = now + 10
                    await asyncio.sleep(min(1, until - now) if until > now else 1)
            finally:
                self.quota_waiting.pop(state, None)
            if use_backup:
                backup = use_backup
            if backup:
                if backup != account.spillover or account.deployment != wire.get("model"):
                    raise ProtocolError("备用部署已移除，续写已停止", 409, "continuation_stopped")
                payload = {**payload, "model": backup}

    def _save_checkpoint(self, owner, response_id, history):
        try:
            self.store.put(owner, "response:" + response_id, history)
        except (ValueError, sqlite3.Error, OSError) as exc:
            logger.warning("续接快照写入失败 错误=%s", exc)
            return False
        return True

    async def generate(self, request, body, send, websocket=False):
        owner = request[OWNER]
        items, wire = prepare_input(self.store, owner["id"], body)
        if websocket and wire.get("generate") is False:
            # A Codex prewarm reserves no model capacity. Its response ID can seed an incremental turn.
            rid = "resp_forge_" + secrets.token_hex(16)
            self._save_checkpoint(owner["id"], rid, items)
            response = {"id": rid, "object": "response", "status": "completed", "output": []}
            await send({"type": "response.created", "response": {**response, "status": "in_progress"}})
            await send({"type": "response.completed", "response": response})
            return
        async with self.scheduler.reserve(owner, request[AUTH], wire.get("model")) as account:
            started = time.monotonic()
            status = "interrupted"
            checkpoint_saved = True
            outputs = {}
            protocol = "WS" if websocket else "HTTP"
            events = self.answer_events(account, request, wire, websocket)
            try:
                async for event in events:
                    kind = event.get("type")
                    if kind == "response.output_item.done":
                        outputs[event.get("output_index", len(outputs))] = event["item"]
                    if kind == "response.completed":
                        resp = event["response"]
                        actual = resp.get("output") or [v for _, v in sorted(outputs.items())]
                        if actual and not resp.get("output"):
                            resp["output"] = actual
                        replay = [replay_item(item) for item in actual]
                        if resp.get("id"):
                            checkpoint_saved = self._save_checkpoint(owner["id"], resp["id"], items + replay)
                    await send(event)
                    if kind in TERMINAL:
                        status = kind if checkpoint_saved else kind + " (续接需完整历史)"
                        if kind in ("response.failed", "error"):
                            error = (event.get("response") or {}).get("error") or event.get("error") or event
                            if error.get("code") in ("model_not_found", "unsupported_model"):
                                self.scheduler.mark_unsupported(account.id, wire.get("model"))
                            if error.get("code") in ("rate_limit_exceeded", "usage_limit_reached"):
                                self.scheduler.rejected(account.id, 429, 60)
                        return
                raise ProtocolError("上游在生成结束前断开", 502)
            except ProtocolError as exc:
                if exc.code in ("model_not_found", "unsupported_model"):
                    self.scheduler.mark_unsupported(account.id, wire.get("model"))
                status = f"{exc.status} {exc.code}"
                raise
            finally:
                await events.aclose()
                self.records.appendleft(
                    {
                        "id": uuid.uuid4().hex,
                        "at": int(time.time()),
                        "owner": owner["name"],
                        "account": account.name,
                        "model": str(body.get("model", ""))[:100],
                        "protocol": protocol,
                        "result": status,
                        "ms": round((time.monotonic() - started) * 1000),
                    }
                )
                try:
                    self.store.record_call(owner["id"])
                except sqlite3.Error as exc:
                    logger.warning("网关请求计数写入失败 错误=%s", exc)

    async def upstream(self, account, headers, wire, websocket):
        url = account.base + "/responses"
        if websocket:
            # Only fall back before a response.create frame has been sent.
            try:
                upstream = await self.client.ws_connect(
                    url,
                    headers=headers,
                    max_msg_size=MAX_RESOURCE,
                )
            except aiohttp.WSServerHandshakeError as exc:
                if exc.status not in (400, 404, 405, 426, 501):
                    if exc.status == 429:
                        # No response body is exposed by aiohttp at the WS handshake; respect Retry-After.
                        limit = quota_limit({"code": "429"}, exc.headers, 429)
                        if limit:
                            raise limit from exc
                    self.scheduler.rejected(account.id, exc.status, 60)
                    raise ProtocolError(f"上游 WebSocket 握手失败（{exc.status}）", exc.status) from exc
            else:
                async with upstream:
                    payload = {**wire, "type": "response.create", "store": False}
                    payload.pop("stream", None)
                    await upstream.send_json(payload)
                    while True:
                        msg = await upstream.receive(timeout=150)
                        if msg.type in (WSMsgType.TEXT, WSMsgType.BINARY):
                            yield json.loads(msg.data)
                        else:
                            raise ProtocolError("上游 WebSocket 意外断开", 502)
                return
        wire = {**wire, "stream": True, "store": False}
        for key in ("generate", "client_metadata", "event_id"):
            wire.pop(key, None)
        async with self.client.post(
            url, headers={**headers, "Accept": "text/event-stream"}, json=wire, allow_redirects=False
        ) as resp:
            await self.check(resp, account)
            async for event in sse_events(resp):
                yield event

    async def responses(self, request):
        body = await request.json()
        if not isinstance(body, dict):
            raise ProtocolError("请求必须为 JSON 对象")
        stream = (
            web.StreamResponse(headers={"Content-Type": "text/event-stream", "Cache-Control": "no-store"})
            if body.get("stream")
            else None
        )
        result = None

        async def send(event):
            nonlocal result
            if stream is not None:
                if not stream.prepared:
                    await stream.prepare(request)
                await stream.write(b"data: " + json.dumps(event, ensure_ascii=False).encode() + b"\n\n")
            elif event["type"] in TERMINAL:
                result = event.get("response") or event

        try:
            await self.generate(request, body, send)
        except (ValueError, aiohttp.ClientError, TimeoutError, OSError) as exc:
            if stream is None or not stream.prepared:
                raise
            await send(
                {
                    "type": "error",
                    "code": "stream_interrupted",
                    "message": str(exc) if isinstance(exc, ValueError) else "上游连接中断",
                }
            )
        if stream is not None:
            await stream.write_eof()
            return stream
        return web.json_response(result)

    async def websocket(self, request):
        owner = request[OWNER]
        owner_id = owner["id"]
        counts = self.websocket_counts()
        total_count = counts.total()
        key_count = counts[owner_id]
        total_limit_reached = total_count >= MAX_WS_CONNECTIONS
        key_limit_reached = key_count >= MAX_WS_CONNECTIONS_PER_KEY
        if total_limit_reached or key_limit_reached:
            self.last_ws_rejection = {
                "at": int(time.time()),
                "ownerId": owner_id,
                "ownerName": owner["name"],
                "keyConnections": key_count,
                "totalConnections": total_count,
                "keyLimitReached": key_limit_reached,
                "totalLimitReached": total_limit_reached,
            }
            logger.warning(
                "WebSocket 握手拒绝 HTTP 429 key_id=%s key_connections=%d/%d "
                "total_connections=%d/%d key_limit_reached=%s total_limit_reached=%s",
                owner_id,
                key_count,
                MAX_WS_CONNECTIONS_PER_KEY,
                total_count,
                MAX_WS_CONNECTIONS,
                key_limit_reached,
                total_limit_reached,
            )
            raise CapacityError("WebSocket 连接已满")
        ws = web.WebSocketResponse(max_msg_size=MAX_BODY, heartbeat=35)
        self.pending_handshakes[ws] = owner_id
        try:
            await ws.prepare(request)
        finally:
            self.pending_handshakes.pop(ws)
        self.sockets[ws] = (owner_id, request.app)
        task = None
        finishing = False

        async def send(event):
            nonlocal finishing
            if event.get("type") in TERMINAL:
                finishing = True
            await ws.send_json(event)

        async def run(body):
            self.generating.add(ws)
            try:
                await self.generate(request, body, send, True)
            except (ValueError, CapacityError, aiohttp.ClientError, TimeoutError, OSError) as exc:
                if not ws.closed:
                    if isinstance(exc, ProtocolError) and exc.code == "previous_response_not_found":
                        await send({
                            "type": "error",
                            "status": exc.status,
                            "error": {
                                "type": "invalid_request_error",
                                "code": exc.code,
                                "message": str(exc),
                                "param": "previous_response_id",
                            },
                        })
                        return
                    code = exc.code if isinstance(exc, ProtocolError) else "gateway_error"
                    await send(
                        {
                            "type": "error",
                            "code": code,
                            "message": str(exc)
                            if isinstance(exc, (ValueError, CapacityError))
                            else "上游连接中断",
                        }
                    )
            finally:
                self.generating.discard(ws)
                if not request[AUTH]() and not ws.closed:
                    await ws.close(code=1001, message=b"service or credential disabled")

        try:
            if not request[LISTENING]():
                await ws.close(code=1001, message=b"listener stopped")
                return ws
            async for msg in ws:
                if not request[AUTH]() or not self.scheduler.accepting:
                    await ws.close(code=1008, message=b"credential or service disabled")
                    break
                if msg.type not in (WSMsgType.TEXT, WSMsgType.BINARY):
                    break
                try:
                    body = json.loads(msg.data)
                    kind = body.pop("type")
                    if kind == "response.create" and finishing and task and not task.done():
                        # The client can submit its next turn while the previous upstream stream is closing.
                        await task
                        if ws.closed or not request[AUTH]() or not self.scheduler.accepting:
                            await ws.close(code=1008, message=b"credential or service disabled")
                            break
                    if kind == "response.cancel":
                        if task and not task.done() and not finishing:
                            task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await task
                            await ws.send_json({"type": "response.cancelled"})
                    elif kind != "response.create" or (task and not task.done()):
                        raise ValueError("当前连接只接受一个正在生成的 response.create")
                    else:
                        finishing = False
                        task = asyncio.create_task(run(body))
                except (ValueError, KeyError, AttributeError, TypeError) as exc:
                    await ws.send_json(
                        {"type": "error", "code": "invalid_request_error", "message": str(exc)}
                    )
        finally:
            self.sockets.pop(ws, None)
            if task:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError, ConnectionError):
                    await task
        return ws
