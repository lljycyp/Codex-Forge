import base64
import json
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from core.constants import USAGE_CACHE_PATH
from core.profile_service import resolve_profile_auth_path


USAGE_URLS = (
    "https://chatgpt.com/backend-api/wham/usage",
    "https://chatgpt.com/api/codex/usage",
)
REQUEST_TIMEOUT_SECONDS = 18


def load_usage_cache():
    """读取本地额度缓存；缓存损坏时返回空对象，避免影响账号列表。"""
    try:
        return json.loads(USAGE_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_usage_cache(cache):
    """保存额度缓存，使用临时文件替换以降低写坏风险。"""
    USAGE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = USAGE_CACHE_PATH.with_name(f".{USAGE_CACHE_PATH.name}.tmp")
    temp_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(USAGE_CACHE_PATH)


def get_cached_profile_usage(profile_name):
    """读取单个账号的额度快照。"""
    usage = load_usage_cache().get(profile_name)
    return usage if isinstance(usage, dict) else None


def refresh_profile_usage(profile_name, profile_dir):
    """刷新单个账号额度并写入缓存。"""
    usage = _build_profile_usage(profile_dir)
    cache = load_usage_cache()
    cache[profile_name] = usage
    save_usage_cache(cache)
    return usage


def refresh_all_profile_usage(profile_dirs):
    """并发刷新全部账号额度，返回按账号名索引的快照。"""
    cache = load_usage_cache()
    if not profile_dirs:
        save_usage_cache(cache)
        return {}

    max_workers = min(4, max(1, len(profile_dirs)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_by_name = {
            executor.submit(_build_profile_usage, Path(profile_dir)): profile_name
            for profile_name, profile_dir in profile_dirs.items()
        }
        for future in as_completed(future_by_name):
            profile_name = future_by_name[future]
            try:
                cache[profile_name] = future.result()
            except Exception as exc:
                cache[profile_name] = _usage_error(f"额度读取失败：{exc}")

    save_usage_cache(cache)
    return {name: cache.get(name) for name in profile_dirs}


def rename_cached_usage(old_name, new_name):
    """账号改名时同步迁移额度缓存。"""
    cache = load_usage_cache()
    if old_name in cache:
        cache[new_name] = cache.pop(old_name)
        save_usage_cache(cache)


def remove_cached_usage(profile_name):
    """账号删除时清理额度缓存。"""
    cache = load_usage_cache()
    if profile_name in cache:
        cache.pop(profile_name, None)
        save_usage_cache(cache)


def _build_profile_usage(profile_dir):
    """读取账号授权并拉取额度接口。"""
    auth_path = resolve_profile_auth_path(Path(profile_dir))
    if not auth_path.exists():
        return _usage_error("未找到登录信息，请先保存当前账号资料")

    try:
        auth_json = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _usage_error(f"登录信息读取失败：{exc}")

    try:
        auth = _extract_auth(auth_json)
    except ValueError as exc:
        return _usage_error(str(exc))

    try:
        payload = _fetch_usage_payload(auth["accessToken"], auth["accountId"])
        usage = _map_usage_payload(payload)
        if not usage.get("planType"):
            usage["planType"] = auth.get("planType")
        usage["error"] = None
        return usage
    except Exception as exc:
        return _usage_error(_normalize_usage_error(str(exc)), auth.get("planType"))


def _extract_auth(auth_json):
    """从 Codex 登录文件里提取额度接口需要的令牌和账号标识。"""
    tokens = _auth_tokens(auth_json)
    if not tokens:
        mode = str(auth_json.get("auth_mode") or "").lower() if isinstance(auth_json, dict) else ""
        if mode and mode not in ("chatgpt", "chatgpt_auth_tokens"):
            raise ValueError("当前账号不是 ChatGPT 登录模式，无法读取额度")
        raise ValueError("登录信息缺少 ChatGPT 令牌，请先重新登录")

    access_token = _clean_string(tokens.get("access_token"))
    id_token = _clean_string(tokens.get("id_token"))
    account_id = _clean_string(tokens.get("account_id") or tokens.get("chatgpt_account_id"))
    if not access_token:
        raise ValueError("登录信息缺少 access_token，无法读取额度")
    if not id_token:
        raise ValueError("登录信息缺少 id_token，无法识别账号额度")

    claims = _decode_jwt_payload(id_token)
    auth_claim = claims.get("https://api.openai.com/auth") if isinstance(claims, dict) else None
    auth_claim = auth_claim if isinstance(auth_claim, dict) else {}
    if not account_id:
        account_id = _clean_string(auth_claim.get("chatgpt_account_id"))
    if not account_id:
        raise ValueError("无法从登录信息识别 ChatGPT 账号编号")

    return {
        "accessToken": access_token,
        "accountId": account_id,
        "planType": _clean_string(auth_claim.get("chatgpt_plan_type")),
    }


def _auth_tokens(auth_json):
    """兼容新旧 auth.json 结构，优先读取 tokens 节点。"""
    if not isinstance(auth_json, dict):
        return None
    tokens = auth_json.get("tokens")
    if isinstance(tokens, dict):
        return tokens
    if "access_token" in auth_json and "id_token" in auth_json:
        return auth_json
    return None


def _fetch_usage_payload(access_token, account_id):
    """依次请求候选额度接口，任一成功即返回接口数据。"""
    errors = []
    for usage_url in USAGE_URLS:
        request = urllib.request.Request(
            usage_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "ChatGPT-Account-Id": account_id,
                "Accept": "application/json",
                "User-Agent": "CodexMultiLauncher/0.1",
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            errors.append(f"{usage_url} -> {exc.code}: {_truncate(body)}")
        except Exception as exc:
            errors.append(f"{usage_url} -> {exc}")

    raise RuntimeError("；".join(errors[:2]) or "未命中任何额度接口")


def _map_usage_payload(payload):
    """把接口返回转换成前端稳定展示的额度快照。"""
    windows = []
    rate_limit = payload.get("rate_limit") if isinstance(payload, dict) else None
    _collect_rate_limit_windows(rate_limit, windows)
    for item in payload.get("additional_rate_limits") or []:
        if isinstance(item, dict):
            _collect_rate_limit_windows(item.get("rate_limit"), windows)

    return {
        "fetchedAt": int(time.time()),
        "planType": _clean_string(payload.get("plan_type")),
        "fiveHour": _to_usage_window(_pick_nearest_window(windows, 5 * 60 * 60)),
        "oneWeek": _to_usage_window(_pick_nearest_window(windows, 7 * 24 * 60 * 60)),
    }


def _collect_rate_limit_windows(rate_limit, windows):
    """收集主窗口和次窗口，后续按时长匹配五小时与一周额度。"""
    if not isinstance(rate_limit, dict):
        return
    for key in ("primary_window", "secondary_window"):
        window = rate_limit.get(key)
        if isinstance(window, dict):
            windows.append(window)


def _pick_nearest_window(windows, target_seconds):
    """选择最接近目标时长的额度窗口。"""
    valid_windows = [
        window
        for window in windows
        if isinstance(window.get("limit_window_seconds"), (int, float))
        and isinstance(window.get("used_percent"), (int, float))
    ]
    if not valid_windows:
        return None
    return min(valid_windows, key=lambda window: abs(window["limit_window_seconds"] - target_seconds))


def _to_usage_window(window):
    """把接口窗口字段转换为前端字段。"""
    if not window:
        return None
    used_percent = _clamp_percent(float(window.get("used_percent", 0)))
    return {
        "usedPercent": used_percent,
        "remainingPercent": _clamp_percent(100 - used_percent),
        "windowSeconds": int(window.get("limit_window_seconds", 0)),
        "resetAt": int(window["reset_at"]) if isinstance(window.get("reset_at"), (int, float)) else None,
    }


def _decode_jwt_payload(token):
    """解析 JWT 第二段载荷，仅读取声明，不验证签名。"""
    parts = token.split(".")
    if len(parts) < 2:
        return {}
    payload = parts[1] + "=" * (-len(parts[1]) % 4)
    try:
        decoded = base64.urlsafe_b64decode(payload.encode("utf-8")).decode("utf-8")
        claims = json.loads(decoded)
        return claims if isinstance(claims, dict) else {}
    except Exception:
        return {}


def _usage_error(message, plan_type=None):
    """生成失败快照，让前端能展示明确原因。"""
    return {
        "fetchedAt": int(time.time()),
        "planType": plan_type,
        "fiveHour": None,
        "oneWeek": None,
        "error": message,
    }


def _normalize_usage_error(message):
    """把常见接口错误转成更容易理解的中文提示。"""
    lowered = message.lower()
    if "401" in lowered or "unauthorized" in lowered or "expired" in lowered:
        return "登录令牌已过期，请启动该账号重新登录后再刷新额度"
    if "403" in lowered:
        return "当前登录信息无权读取额度，请确认账号状态"
    return f"额度读取失败：{message}"


def _clean_string(value):
    """清理可选字符串字段。"""
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _clamp_percent(value):
    """限制百分比范围，避免异常接口值撑破界面。"""
    return max(0, min(100, value))


def _truncate(value, limit=140):
    """截断接口错误正文，避免过长内容进入界面。"""
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return f"{text[:limit]}..."
