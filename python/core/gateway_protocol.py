import asyncio
import base64
import contextlib
import json
import mimetypes
import secrets
import time
import uuid
from collections import deque
from collections.abc import Callable
from pathlib import PurePath

import aiohttp
from aiohttp import WSMsgType, web

from core.gateway_accounts import CHATGPT_BASE, CapacityError
from core.gateway_store import MAX_RESOURCE

OWNER = web.RequestKey[dict]("gateway_owner")
AUTH = web.RequestKey[Callable[[], dict | None]]("gateway_auth")
MAX_BODY = 16 * 1024 * 1024
TERMINAL = {"response.completed", "response.failed", "response.incomplete", "response.cancelled", "error"}


class ProtocolError(ValueError):
    def __init__(self, message, status=400, code="invalid_request_error"):
        super().__init__(message)
        self.status, self.code = status, code


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
        self.generating = set()
        self.uploads = 0

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
                request[OWNER], request[AUTH] = owner, auth
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
        self.scheduler.rejected(account.id, response.status, int(wait) if wait.isdigit() else 60)
        # Provider diagnostics can contain account identifiers; expose the protocol code, never credentials.
        code = "upstream_error"
        try:
            info = json.loads(await response.content.read(8192))
            value = (info.get("error") or {}).get("code")
            if isinstance(value, str) and value.replace("_", "").isalnum() and len(value) <= 64:
                code = value
        except (ValueError, AttributeError):
            pass
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
        async with self.scheduler.reserve(request[OWNER], request[AUTH]) as account:
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

    async def generate(self, request, body, send, websocket=False):
        owner = request[OWNER]
        items, wire = prepare_input(self.store, owner["id"], body)
        if websocket and wire.get("generate") is False:
            # A Codex prewarm reserves no model capacity. Its response ID can seed an incremental turn.
            rid = "resp_forge_" + secrets.token_hex(16)
            self.store.put(owner["id"], "response:" + rid, items)
            response = {"id": rid, "object": "response", "status": "completed", "output": []}
            await send({"type": "response.created", "response": {**response, "status": "in_progress"}})
            await send({"type": "response.completed", "response": response})
            return
        async with self.scheduler.reserve(owner, request[AUTH], wire.get("model")) as account:
            started = time.monotonic()
            status = "interrupted"
            checkpoint_saved = True
            outputs = {}
            headers = self.headers(account, request)
            protocol = "WS" if websocket else "HTTP"
            try:
                async for event in self.upstream(account, headers, wire, websocket):
                    kind = event.get("type")
                    if kind == "response.output_item.done":
                        outputs[event.get("output_index", len(outputs))] = event["item"]
                    if kind == "response.completed":
                        resp = event["response"]
                        actual = resp.get("output") or [v for _, v in sorted(outputs.items())]
                        if actual and not resp.get("output"):
                            resp["output"] = actual
                        replay = []
                        for item in actual:
                            item = dict(item)
                            if item.get("type") in (
                                "message",
                                "function_call",
                                "custom_tool_call",
                                "reasoning",
                            ):
                                item.pop("id", None)
                            replay.append(item)
                        if resp.get("id"):
                            try:
                                self.store.put(owner["id"], "response:" + resp["id"], items + replay)
                            except ValueError:
                                # The upstream generation already completed. A client can resume with full input.
                                checkpoint_saved = False
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
                self.store.db.execute("UPDATE owners SET calls=calls+1 WHERE id=?", (owner["id"],))

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
        owner = request[OWNER]["id"]
        if len(self.sockets) >= 64 or sum(1 for key, _ in self.sockets.values() if key == owner) >= 12:
            raise CapacityError("WebSocket 连接已满")
        ws = web.WebSocketResponse(max_msg_size=MAX_BODY, heartbeat=35)
        await ws.prepare(request)
        self.sockets[ws] = (owner, request.app)
        task = None

        async def run(body):
            self.generating.add(ws)
            try:
                await self.generate(request, body, ws.send_json, True)
            except (ValueError, CapacityError, aiohttp.ClientError, TimeoutError, OSError) as exc:
                if not ws.closed:
                    code = exc.code if isinstance(exc, ProtocolError) else "gateway_error"
                    await ws.send_json(
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
            async for msg in ws:
                if not request[AUTH]() or not self.scheduler.accepting:
                    await ws.close(code=1008, message=b"credential or service disabled")
                    break
                if msg.type not in (WSMsgType.TEXT, WSMsgType.BINARY):
                    break
                try:
                    body = json.loads(msg.data)
                    kind = body.pop("type")
                    if kind == "response.cancel":
                        if task and not task.done():
                            task.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await task
                            await ws.send_json({"type": "response.cancelled"})
                    elif kind != "response.create" or (task and not task.done()):
                        raise ValueError("当前连接只接受一个正在生成的 response.create")
                    else:
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
