import base64
import hashlib
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


OAUTH_ISSUER = "https://auth.openai.com"
OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OAUTH_SCOPE = "openid profile email offline_access api.connectors.read api.connectors.invoke"
OAUTH_ORIGINATOR = "codex_vscode"
OAUTH_REDIRECT_PORT = 1455
OAUTH_TIMEOUT_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 30


def login_with_browser():
    """打开浏览器完成 OpenAI 授权，并返回可写入 Codex 的 auth.json 内容。"""
    pending = _build_oauth_request()
    server = _CallbackServer(("127.0.0.1", OAUTH_REDIRECT_PORT), _CallbackHandler)
    server.expected_state = pending["state"]
    server.callback_error = None
    server.callback_code = None

    try:
        if not webbrowser.open(pending["auth_url"]):
            raise RuntimeError(f"无法自动打开浏览器，请手动访问：{pending['auth_url']}")
        _wait_for_callback(server)
    finally:
        server.server_close()

    if server.callback_error:
        raise RuntimeError(server.callback_error)
    if not server.callback_code:
        raise RuntimeError("未收到授权回调，请重新登录")

    token_response = _exchange_authorization_code(server.callback_code, pending)
    return _build_auth_json(token_response)


def _build_oauth_request():
    """生成授权链接和后续换取令牌所需的校验参数。"""
    state = secrets.token_hex(16)
    code_verifier = f"{secrets.token_hex(32)}{secrets.token_hex(32)}"
    code_challenge = _base64_url(hashlib.sha256(code_verifier.encode("utf-8")).digest())
    redirect_uri = f"http://localhost:{OAUTH_REDIRECT_PORT}/auth/callback"
    params = {
        "response_type": "code",
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": OAUTH_SCOPE,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "id_token_add_organizations": "true",
        "codex_cli_simplified_flow": "true",
        "originator": OAUTH_ORIGINATOR,
    }
    auth_url = f"{OAUTH_ISSUER}/oauth/authorize?{urllib.parse.urlencode(params)}"
    return {
        "auth_url": auth_url,
        "redirect_uri": redirect_uri,
        "state": state,
        "code_verifier": code_verifier,
    }


def _wait_for_callback(server):
    """在本地端口等待浏览器授权回调，超时后主动结束流程。"""
    deadline = time.monotonic() + OAUTH_TIMEOUT_SECONDS
    server.timeout = 0.5
    while time.monotonic() < deadline:
        server.handle_request()
        if server.callback_code or server.callback_error:
            return
    raise TimeoutError("等待浏览器授权超时，请重新新增账号")


def _exchange_authorization_code(code, pending):
    """用回调 code 换取 Codex 可用的登录令牌。"""
    token_url = f"{OAUTH_ISSUER}/oauth/token"
    form = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": pending["redirect_uri"],
            "client_id": OAUTH_CLIENT_ID,
            "code_verifier": pending["code_verifier"],
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        token_url,
        data=form,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "codex-forge/0.1",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:240]
        raise RuntimeError(f"换取登录令牌失败：{exc.code} {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"换取登录令牌失败：{exc}") from exc


def _build_auth_json(token_response):
    """把授权响应转换为 Codex auth.json 的标准结构。"""
    access_token = _required_string(token_response, "access_token")
    refresh_token = _required_string(token_response, "refresh_token")
    id_token = _required_string(token_response, "id_token")
    account_id = _extract_account_id(id_token)
    return {
        "OPENAI_API_KEY": None,
        "auth_mode": "chatgpt",
        "last_refresh": _rfc3339_now(),
        "tokens": {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "id_token": id_token,
            "account_id": account_id,
        },
    }


def _extract_account_id(id_token):
    """从 id_token 声明中读取 ChatGPT 账号编号。"""
    claims = _decode_jwt_payload(id_token)
    auth_claim = claims.get("https://api.openai.com/auth")
    if isinstance(auth_claim, dict):
        account_id = str(auth_claim.get("chatgpt_account_id") or "").strip()
        if account_id:
            return account_id
    raise RuntimeError("无法从授权结果识别 ChatGPT 账号编号")


def _decode_jwt_payload(token):
    """解码 JWT（JSON 网络令牌）的载荷部分。"""
    parts = token.split(".")
    if len(parts) < 2:
        raise RuntimeError("授权结果中的 id_token 格式无效")
    payload = parts[1]
    padding = "=" * ((4 - len(payload) % 4) % 4)
    try:
        decoded = base64.urlsafe_b64decode(f"{payload}{padding}")
        return json.loads(decoded.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"解析授权身份信息失败：{exc}") from exc


def _required_string(payload, key):
    """读取必需字符串字段，缺失时给出明确错误。"""
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    raise RuntimeError(f"授权响应缺少 {key}")


def _base64_url(raw):
    """生成不带填充符的 URL 安全文本。"""
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _rfc3339_now():
    """生成 Codex auth.json 使用的 UTC 时间文本。"""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class _CallbackServer(ThreadingHTTPServer):
    allow_reuse_address = True


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """处理浏览器回跳到本地端口的授权结果。"""
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        state = query.get("state", [""])[0]
        if state != self.server.expected_state:
            self.server.callback_error = "授权回调校验失败，请重新新增账号"
            self._send_page("授权失败，请关闭此页面后重试。", status=400)
            return

        error = query.get("error", [""])[0]
        if error:
            description = query.get("error_description", [error])[0]
            self.server.callback_error = f"授权失败：{description}"
            self._send_page("授权失败，请关闭此页面后重试。", status=400)
            return

        code = query.get("code", [""])[0]
        if not code:
            self.server.callback_error = "授权回调缺少 code 参数"
            self._send_page("授权失败，请关闭此页面后重试。", status=400)
            return

        self.server.callback_code = code
        self._send_page("授权完成，可以回到 Codex Forge。")

    def log_message(self, _format, *_args):
        """禁止把本地回调请求输出到后端标准流。"""
        return

    def _send_page(self, message, status=200):
        body = f"<!doctype html><meta charset='utf-8'><title>Codex</title><p>{message}</p>"
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)
