"""Local, opt-in Responses gateway. Account files are read only; no token refresh."""

import hashlib
import hmac
import http.server
import json
import secrets
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

from core import db
from core.auth_service import auth_tokens, decode_jwt_payload
from core.config_store import load_config
from core.constants import CONFIG_DIR
from core.secure_store import protect_bytes, unprotect_bytes

UPSTREAM = "https://chatgpt.com/backend-api/codex/responses"
MAX_BODY = 8 * 1024 * 1024
MAX_CONCURRENT = 2
MAX_CONNECTIONS = 32


def save_enabled(enabled):
    # Update one setting, without rewriting profiles or concurrent settings edits.
    with db.connect() as connection:
        connection.execute(
            "INSERT INTO settings (key, value_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            ("load_balancer_enabled", json.dumps(enabled), int(time.time())),
        )


def load_key():
    path = CONFIG_DIR / "load-balancer-key.bin"
    if path.exists():
        return unprotect_bytes(path.read_bytes()).decode("utf-8")
    key = "forge-" + secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Only the single Electron-owned gateway process creates the key.
    path.write_bytes(protect_bytes(key.encode("utf-8")))
    return key


def read_accounts():
    config = load_config()
    root = Path(config["profile_root"]).resolve()
    usage = db.load_usage_cache()
    accounts = []
    identities = set()
    for record in db.list_profile_records():
        directory = (root / record["dir_name"]).resolve()
        if not directory.is_relative_to(root):
            continue
        # Multi-instance credentials can be newer; use the newest valid copy.
        paths = [directory / "auth.json"]
        if config.get("launch_mode") == "multi":
            paths.append(directory / "CodexHome" / "auth.json")
        item = {"id": record["id"], "name": record["display_name"], "reason": "认证缺失或无效"}
        candidates = []
        for path in paths:
            try:
                if not path.resolve().is_relative_to(root):
                    continue
                tokens = auth_tokens(json.loads(path.read_text(encoding="utf-8-sig"))) or {}
                token = tokens.get("access_token")
                claims = decode_jwt_payload(token) if isinstance(token, str) else {}
                auth = claims.get("https://api.openai.com/auth") or {}
                account_id = tokens.get("account_id") or tokens.get("chatgpt_account_id") or auth.get("chatgpt_account_id")
                user_id = claims.get("sub") or auth.get("chatgpt_user_id")
                if token and account_id and user_id:
                    candidates.append((path.stat().st_mtime, token, account_id, user_id, claims.get("exp", 0)))
            except (OSError, ValueError, TypeError, AttributeError):
                continue
        if candidates:
            _, token, account_id, user_id, expires = max(candidates, key=lambda entry: entry[0])
            identity = hashlib.sha256(f"{account_id}|{user_id}".encode()).hexdigest()
            item.update(identity=identity, token=token, account_id=account_id)
            if identity in identities:
                item["reason"] = "重复账号，共用原账号容量"
            else:
                identities.add(identity)
                item["reason"] = "" if isinstance(expires, (int, float)) and expires > time.time() + 60 else "令牌即将过期，请刷新额度或重新授权"
                snapshot = usage.get(record["display_name"]) or {}
                window = snapshot.get("oneWeek") or {}
                reset = window.get("resetAt")
                # A past reset invalidates the cached exhausted state.
                if (snapshot.get("spendControlReached") or window.get("remainingPercent") == 0) and (
                    not isinstance(reset, (int, float)) or reset > time.time()
                ):
                    item["reason"] = "额度已耗尽，请刷新额度后重试"
        accounts.append(item)
    return accounts


def portable_request(body):
    if not isinstance(body, dict) or not isinstance(body.get("model"), str) or not body["model"]:
        return "需要有效的 model"
    if body.get("stream") is not True or body.get("store") is not False:
        return "实验网关仅支持 stream=true、store=false 的 Responses 请求"
    if not isinstance(body.get("input"), list):
        return "需要包含完整历史的 input 数组"
    if body.get("previous_response_id") or body.get("conversation") or body.get("background"):
        return "暂不支持账号专属续接状态，请使用包含完整历史的新会话"

    def has_account_state(value):
        if isinstance(value, dict):
            return bool(value.get("file_id")) or value.get("type") in ("compaction", "item_reference") or any(
                has_account_state(entry) for entry in value.values()
            )
        return isinstance(value, list) and any(has_account_state(entry) for entry in value)

    return "暂不支持文件 ID 或压缩状态的跨账号迁移" if has_account_state(body["input"]) else ""


class Gateway:
    def __init__(self, account_reader=read_accounts, opener=None):
        self.account_reader = account_reader
        # Never follow an upstream redirect with account credentials.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None
        self.opener = opener or urllib.request.build_opener(NoRedirect())
        self.lock = threading.Lock()
        self.enabled = False
        self.server = None
        self.key = ""
        self.port = 0
        self.active = {}
        self.last_used = {}
        self.cooldowns = {}
        self.counter = 0
        self.recent = deque(maxlen=30)

    def start(self, port, key):
        if self.server:
            return
        gateway = self

        class Server(http.server.ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = False
            request_queue_size = MAX_CONNECTIONS

            def __init__(self, address, handler):
                self.slots = threading.BoundedSemaphore(MAX_CONNECTIONS)
                super().__init__(address, handler)

            def process_request(self, request, client_address):
                if not self.slots.acquire(blocking=False):
                    self.shutdown_request(request)
                    return
                try:
                    super().process_request(request, client_address)
                except Exception:
                    self.slots.release()
                    raise

            def process_request_thread(self, request, client_address):
                try:
                    super().process_request_thread(request, client_address)
                finally:
                    self.slots.release()

        class Handler(http.server.BaseHTTPRequestHandler):
            def setup(self):
                super().setup()
                self.connection.settimeout(60)

            def log_message(self, format, *args):
                pass

            def error_json(self, status, text):
                data = json.dumps({"error": {"message": text, "type": "forge_gateway_error"}}, ensure_ascii=False).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                self.error_json(400, "实验网关仅支持 POST /v1/responses，不支持 WebSocket")

            def do_POST(self):
                try:
                    self.forward()
                except (OSError, TimeoutError):
                    pass  # Client disconnected; forward() always releases its lease.

            def forward(self):
                if not hmac.compare_digest(self.headers.get("Authorization", "").encode(), ("Bearer " + gateway.key).encode()):
                    self.error_json(401, "无效的 Forge Key")
                    return
                if self.path != "/v1/responses":
                    self.error_json(404, "实验网关仅支持 /v1/responses")
                    return
                if self.headers.get("Transfer-Encoding") or self.headers.get("Content-Encoding", "identity") != "identity":
                    self.error_json(400, "暂不支持分块或压缩的请求正文")
                    return
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    size = 0
                if not 0 < size <= MAX_BODY:
                    self.error_json(413, "请求正文为空或超过 8 MiB")
                    return
                try:
                    raw = self.rfile.read(size)
                    body = json.loads(raw)
                    error = portable_request(body)
                except (ValueError, RecursionError, UnicodeError):
                    self.error_json(400, "无效的 JSON 请求")
                    return
                if error or self.headers.get("x-codex-turn-state"):
                    self.error_json(400, error or "暂不支持账号专属 turn state")
                    return
                try:
                    account, reason = gateway.acquire()
                except Exception:
                    self.error_json(503, "读取现有账号资料失败")
                    return
                if account is None:
                    self.error_json(503, reason)
                    return
                start = time.monotonic()
                status = 502
                headers_sent = False
                outcome = "failed"
                try:
                    headers = {"Authorization": "Bearer " + account["token"],
                               "ChatGPT-Account-Id": account["account_id"],
                               "Content-Type": "application/json", "Accept": "text/event-stream"}
                    for name in ("User-Agent", "originator", "OpenAI-Beta"):
                        if self.headers.get(name):
                            headers[name] = self.headers[name]
                    request = urllib.request.Request(UPSTREAM, data=raw, headers=headers)
                    with gateway.opener.open(request, timeout=60) as upstream:
                        status = upstream.status
                        self.send_response(status)
                        self.send_header("Content-Type", "text/event-stream")
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("Connection", "close")
                        self.end_headers()
                        headers_sent = True
                        while True:
                            if time.monotonic() - start > 300:
                                raise TimeoutError()
                            line = upstream.readline(MAX_BODY + 1)
                            if not line:
                                break
                            if len(line) > MAX_BODY:
                                raise ValueError("SSE frame too large")
                            self.wfile.write(line)
                            self.wfile.flush()
                            if line.startswith(b"data: "):
                                try:
                                    event = json.loads(line[6:])
                                    event_type = event.get("type")
                                    if event_type == "response.completed":
                                        outcome = "completed"
                                    elif event_type in ("error", "response.failed"):
                                        outcome = "upstream_error"
                                        gateway.cooldown(account, 30)
                                except (ValueError, AttributeError):
                                    pass
                        if outcome == "failed":
                            outcome = "incomplete_stream"
                except urllib.error.HTTPError as exc:
                    status = exc.code
                    delay = 30
                    try:
                        payload = json.loads(exc.read(65536))
                        details = payload.get("error") or {}
                        reset = details.get("resets_at")
                        if isinstance(reset, (int, float)):
                            delay = max(1, reset - time.time())
                        elif exc.headers.get("Retry-After", "").isdigit():
                            delay = int(exc.headers["Retry-After"])
                    except (ValueError, AttributeError, OSError):
                        pass
                    finally:
                        exc.close()
                    if status in (401, 403, 429) or status >= 500:
                        gateway.cooldown(account, max(delay, 60 if status in (401, 403) else 1))
                    self.error_json(status, f"上游返回 {status}；本次请求未自动重放，请检查账号额度或认证")
                except Exception:
                    if headers_sent:
                        outcome = "interrupted"
                    else:
                        self.error_json(502, "上游连接失败，本次请求未自动重放")
                finally:
                    gateway.release(account, body["model"], status, outcome, time.monotonic() - start)

        server = Server(("127.0.0.1", port), Handler)
        self.key = key
        self.port = server.server_port
        self.server = server
        with self.lock:
            self.enabled = True
        threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.1}, daemon=True).start()

    def stop(self):
        with self.lock:
            self.enabled = False
        server, self.server = self.server, None
        if server:
            server.shutdown()
            server.server_close()

    def acquire(self):
        accounts = self.account_reader()
        with self.lock:
            if not self.enabled:
                return None, "负载均衡已关闭"
            available = [a for a in accounts if not a["reason"] and self.cooldowns.get(a["identity"], 0) <= time.time()]
            available = [a for a in available if self.active.get(a["identity"], 0) < MAX_CONCURRENT]
            if not available:
                return None, "没有可用账号或所有账号已满载，请稍后重试"
            selected = min(available, key=lambda a: (self.active.get(a["identity"], 0), self.last_used.get(a["identity"], 0)))
            identity = selected["identity"]
            self.counter += 1
            self.last_used[identity] = self.counter
            self.active[identity] = self.active.get(identity, 0) + 1
            return selected, ""

    def cooldown(self, account, seconds):
        with self.lock:
            self.cooldowns[account["identity"]] = time.time() + min(max(seconds, 1), 7 * 86400)

    def release(self, account, model, status, outcome, seconds):
        with self.lock:
            identity = account["identity"]
            self.active[identity] = max(0, self.active.get(identity, 0) - 1)
            self.recent.appendleft({"account": account["name"], "model": model, "status": status,
                                    "outcome": outcome, "seconds": round(seconds, 1), "at": int(time.time())})

    def status(self):
        accounts = self.account_reader() if self.enabled else []
        with self.lock:
            return {"enabled": self.enabled, "running": self.server is not None,
                    "baseUrl": f"http://127.0.0.1:{self.port or 19380}/v1",
                    "activeRequests": sum(self.active.values()), "maxConcurrentPerAccount": MAX_CONCURRENT,
                    "accounts": [{"id": a["id"], "name": a["name"], "active": self.active.get(a.get("identity"), 0),
                                  "reason": a["reason"] or ("冷却中" if self.cooldowns.get(a.get("identity"), 0) > time.time() else ""),
                                  "cooldownUntil": self.cooldowns.get(a.get("identity"), 0)} for a in accounts],
                    "recentRequests": list(self.recent)}


def run_service():
    gateway = Gateway()
    config = load_config()
    try:
        if config.get("load_balancer_enabled"):
            gateway.start(int(config.get("load_balancer_port", 19380)), load_key())
        print(json.dumps({"id": 0, "ok": True, "data": gateway.status()}), flush=True)
        for line in sys.stdin:
            message = {}
            try:
                message = json.loads(line)
                command = message.get("command")
                if command == "set_enabled":
                    enabled = message.get("enabled")
                    if not isinstance(enabled, bool):
                        raise ValueError("enabled 必须是布尔值")
                    if enabled:
                        gateway.start(int(config.get("load_balancer_port", 19380)), load_key())
                        try:
                            save_enabled(True)
                        except Exception:
                            gateway.stop()
                            raise
                    else:
                        save_enabled(False)
                        gateway.stop()
                    data = gateway.status()
                elif command == "get_key":
                    if not gateway.enabled:
                        raise ValueError("请先开启负载均衡")
                    data = {"key": gateway.key}
                elif command == "launch_client":
                    if not gateway.enabled:
                        raise ValueError("请先开启负载均衡")
                    from core.load_balancer_client import launch_client
                    data = launch_client(load_config(), gateway.status()["baseUrl"], gateway.key)
                elif command == "status":
                    data = gateway.status()
                else:
                    raise ValueError("未知网关命令")
                result = {"id": message.get("id"), "ok": True, "data": data}
            except Exception as exc:
                result = {"id": message.get("id"), "ok": False, "error": str(exc) if isinstance(exc, ValueError) else "网关操作失败：" + type(exc).__name__}
            print(json.dumps(result, ensure_ascii=False), flush=True)
    finally:
        gateway.stop()
        # EOF means Forge exited. No detached listener or replays survive it.
    return 0
