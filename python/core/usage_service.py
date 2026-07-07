import contextlib
import json
import os
import shutil
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from core.auth_service import ensure_fresh_auth, extract_auth
from core.constants import USAGE_CACHE_PATH
from core.profile_service import (
    get_active_config_path,
    resolve_profile_auth_path,
    write_profile_auth_json,
)


USAGE_URLS = (
    "https://chatgpt.com/backend-api/wham/usage",
)
REQUEST_TIMEOUT_SECONDS = 18
TRANSIENT_RETRY_COUNT = 2
TRANSIENT_RETRY_DELAY_SECONDS = 1.2
DEFAULT_CHATGPT_BASE_URL = "https://chatgpt.com"
BACKEND_API_PREFIX = "/backend-api"


def load_usage_cache():
    """读取本地额度缓存；缓存损坏时返回空对象，避免影响账号列表。"""
    try:
        return json.loads(USAGE_CACHE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_usage_cache(cache):
    """保存额度缓存，使用临时文件替换以降低写坏风险。"""
    USAGE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    temp_path = USAGE_CACHE_PATH.with_name(f".{USAGE_CACHE_PATH.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(USAGE_CACHE_PATH)


def get_cached_profile_usage(profile_name):
    """读取单个账号的额度快照。"""
    usage = load_usage_cache().get(profile_name)
    return usage if isinstance(usage, dict) else None


def refresh_profile_usage(profile_name, profile_dir, share_system_config=False, use_codex_home_auth=False):
    """刷新单个账号额度并写入缓存。"""
    started_at = time.time()
    usage = _build_profile_usage(
        profile_dir,
        share_system_config=share_system_config,
        use_codex_home_auth=use_codex_home_auth,
    )
    cache = _merge_usage_results({profile_name: usage}, started_at)
    return cache.get(profile_name, usage)


def refresh_all_profile_usage(profile_dirs, share_system_config=False, use_codex_home_auth=False):
    """受控并发刷新全部账号额度，返回按账号名索引的快照。"""
    started_at = time.time()
    if not profile_dirs:
        cache = load_usage_cache()
        save_usage_cache(cache)
        return {}

    results = {}
    for profile_name, profile_dir in profile_dirs.items():
        try:
            results[profile_name] = _build_profile_usage(
                Path(profile_dir),
                share_system_config=share_system_config,
                use_codex_home_auth=use_codex_home_auth,
            )
        except Exception as exc:
            results[profile_name] = _usage_error(f"额度读取失败：{exc}")

    cache = _merge_usage_results(results, started_at)
    return {name: cache.get(name) for name in profile_dirs}


def _merge_usage_results(results, started_at):
    """合并刷新结果；避免较早启动的后台刷新覆盖较晚完成的手动刷新。"""
    with _file_lock(USAGE_CACHE_PATH.with_name(f".{USAGE_CACHE_PATH.name}.lock")):
        cache = load_usage_cache()
        for profile_name, usage in results.items():
            current = cache.get(profile_name)
            current_fetched_at = current.get("fetchedAt") if isinstance(current, dict) else None
            if isinstance(current_fetched_at, (int, float)) and current_fetched_at > started_at:
                continue
            if _should_keep_current_usage(current, usage):
                continue
            cache[profile_name] = usage
        save_usage_cache(cache)
        return cache


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


def _build_profile_usage(profile_dir, share_system_config=False, use_codex_home_auth=False):
    """读取账号授权并拉取额度接口。"""
    profile_dir = Path(profile_dir)
    auth_path = _resolve_usage_auth_path(profile_dir, use_codex_home_auth)
    if not auth_path.exists():
        return _usage_error("未找到登录信息，请先保存当前账号资料")

    try:
        auth_json = json.loads(auth_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return _usage_error(f"登录信息读取失败：{exc}")

    try:
        auth_json, refresh_error = _ensure_profile_auth_fresh(auth_path, auth_json)
        auth = extract_auth(auth_json)
    except ValueError as exc:
        return _usage_error(str(exc))
    except Exception as exc:
        refresh_error = str(exc)
        try:
            auth = extract_auth(auth_json)
        except ValueError as auth_exc:
            return _usage_error(_normalize_usage_error(f"{auth_exc}；令牌刷新失败：{refresh_error}"))

    _sync_usage_auth_to_profile(profile_dir, auth_path, use_codex_home_auth)

    try:
        config_path = _resolve_usage_config_path(profile_dir, share_system_config, use_codex_home_auth)
        payload = _fetch_usage_payload(
            auth["accessToken"],
            auth["accountId"],
            config_path,
        )
        usage = _map_usage_payload(payload)
        if not usage.get("planType"):
            usage["planType"] = auth.get("planType")
        usage["error"] = None
        _sync_usage_auth_to_profile(profile_dir, auth_path, use_codex_home_auth)
        return usage
    except Exception as exc:
        message = str(exc)
        if _should_retry_with_token_refresh(message):
            try:
                auth_json, _ = _ensure_profile_auth_fresh(auth_path, auth_json, force=True)
                auth = extract_auth(auth_json)
                config_path = _resolve_usage_config_path(profile_dir, share_system_config, use_codex_home_auth)
                payload = _fetch_usage_payload(
                    auth["accessToken"],
                    auth["accountId"],
                    config_path,
                )
                usage = _map_usage_payload(payload)
                if not usage.get("planType"):
                    usage["planType"] = auth.get("planType")
                usage["error"] = None
                _sync_usage_auth_to_profile(profile_dir, auth_path, use_codex_home_auth)
                return usage
            except Exception as retry_exc:
                message = f"{message}；刷新令牌重试失败：{retry_exc}"
        elif refresh_error:
            message = f"{message}；令牌刷新失败：{refresh_error}"
        return _usage_error(_normalize_usage_error(message), auth.get("planType"))


def _resolve_usage_auth_path(profile_dir, use_codex_home_auth=False):
    """多开模式优先读取 Codex 进程正在使用的 CODEX_HOME/auth.json。"""
    profile_dir = Path(profile_dir)
    codex_home_auth_path = profile_dir / "CodexHome" / "auth.json"
    if use_codex_home_auth and codex_home_auth_path.exists():
        return codex_home_auth_path
    return resolve_profile_auth_path(profile_dir)


def _resolve_usage_config_path(profile_dir, share_system_config=False, use_codex_home_auth=False):
    """switch 使用系统配置；multi 使用 CodexHome/config.toml。"""
    profile_dir = Path(profile_dir)
    codex_home_config_path = profile_dir / "CodexHome" / "config.toml"
    if use_codex_home_auth:
        return codex_home_config_path
    return get_active_config_path()


def _sync_usage_auth_to_profile(profile_dir, auth_path, use_codex_home_auth=False):
    """额度刷新使用 CodexHome/auth.json 时，把最新 token 回写到账号主资料。"""
    if not use_codex_home_auth:
        return
    auth_path = Path(auth_path)
    profile_auth_path = Path(profile_dir) / "auth.json"
    if auth_path.exists() and auth_path != profile_auth_path:
        shutil.copy2(auth_path, profile_auth_path)


def _ensure_profile_auth_fresh(auth_path, auth_json, force=False):
    """必要时刷新账号令牌，并把新 auth.json 写回账号目录。"""
    auth_path = Path(auth_path)
    with _file_lock(auth_path.with_name(f".{auth_path.name}.refresh.lock")):
        latest_auth_json = auth_json
        try:
            latest_auth_json = json.loads(auth_path.read_text(encoding="utf-8"))
        except Exception:
            pass
        refreshed_auth_json, refreshed = ensure_fresh_auth(latest_auth_json, force=force)
        if refreshed:
            write_profile_auth_json(auth_path, refreshed_auth_json)
        return refreshed_auth_json, None


def _fetch_usage_payload(access_token, account_id, config_path=None):
    """依次请求候选额度接口，任一成功即返回接口数据。"""
    errors = []
    for usage_url in _resolve_usage_urls(config_path):
        request = urllib.request.Request(
            usage_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "ChatGPT-Account-Id": account_id,
                "Accept": "application/json",
                "User-Agent": "CodexForge/0.1",
            },
            method="GET",
        )
        try:
            return _request_usage_json(request)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            errors.append(f"{usage_url} -> {exc.code}: {_truncate(body)}")
        except Exception as exc:
            errors.append(f"{usage_url} -> {exc}")

    raise RuntimeError("；".join(errors[:2]) or "未命中任何额度接口")


def _request_usage_json(request):
    """请求额度接口；临时网络错误会短暂重试，最终失败才返回错误。"""
    last_error = None
    for attempt in range(TRANSIENT_RETRY_COUNT + 1):
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
                return json.loads(body)
        except urllib.error.HTTPError:
            raise
        except Exception as exc:
            last_error = exc
            if attempt >= TRANSIENT_RETRY_COUNT or not _is_transient_network_error(str(exc)):
                raise
            time.sleep(TRANSIENT_RETRY_DELAY_SECONDS * (attempt + 1))
    if last_error is not None:
        raise last_error
    raise RuntimeError("额度读取失败")


def _resolve_usage_urls(config_path=None):
    """按账号配置和默认地址生成额度接口候选列表。"""
    base_url = _read_chatgpt_base_url(config_path) or DEFAULT_CHATGPT_BASE_URL
    normalized = base_url.rstrip("/")
    parsed = urllib.parse.urlparse(normalized)
    if not parsed.scheme or not parsed.netloc:
        normalized = DEFAULT_CHATGPT_BASE_URL
    candidates = []
    if normalized.endswith(BACKEND_API_PREFIX):
        candidates.append(f"{normalized}/wham/usage")
    else:
        candidates.append(f"{normalized}{BACKEND_API_PREFIX}/wham/usage")
    candidates.extend(USAGE_URLS)
    return _dedupe(candidates)


def _read_chatgpt_base_url(config_path):
    """从当前生效的 config.toml 读取自定义 ChatGPT 地址。"""
    if not config_path or not Path(config_path).exists():
        return None
    try:
        for line in Path(config_path).read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith("chatgpt_base_url"):
                continue
            _key, value = stripped.split("=", 1)
            value = value.strip().strip('"').strip("'")
            if value:
                return value
    except Exception:
        return None
    return None


def _dedupe(values):
    """保持顺序去重候选地址。"""
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _map_usage_payload(payload):
    """把接口返回转换成前端稳定展示的额度快照。"""
    windows = []
    rate_limit = payload.get("rate_limit") if isinstance(payload, dict) else None
    _collect_rate_limit_windows(rate_limit, windows)
    for item in payload.get("additional_rate_limits") or []:
        if isinstance(item, dict):
            _collect_rate_limit_windows(item.get("rate_limit"), windows)

    return {
        "fetchedAt": time.time(),
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


def _usage_error(message, plan_type=None):
    """生成失败快照，让前端能展示明确原因。"""
    return {
        "fetchedAt": time.time(),
        "planType": plan_type,
        "fiveHour": None,
        "oneWeek": None,
        "error": message,
    }


def _normalize_usage_error(message):
    """把常见接口错误转成更容易理解的中文提示。"""
    lowered = message.lower()
    if "invalid_grant" in lowered or "refresh_token_reused" in lowered:
        return "登录刷新令牌已失效，请通过浏览器重新授权该账号"
    if "缺少 refresh_token" in lowered:
        return "登录信息缺少 refresh_token，无法自动刷新，请重新授权"
    if "401" in lowered or "unauthorized" in lowered or "expired" in lowered:
        return "登录令牌已过期，请重新授权后再刷新额度"
    if "403" in lowered:
        return "当前登录信息无权读取额度，请确认账号状态"
    if "timed out" in lowered or "timeout" in lowered:
        return "额度读取超时，请检查网络或代理后重试"
    return f"额度读取失败：{message}"


def _should_retry_with_token_refresh(message):
    """识别可通过刷新令牌重试的额度接口错误。"""
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "401",
            "unauthorized",
            "expired",
            "invalid token",
            "provided authentication token",
        )
    )


def _is_transient_network_error(message):
    """识别短时间重试可能恢复的网络错误。"""
    lowered = message.lower()
    return any(
        marker in lowered
        for marker in (
            "timed out",
            "timeout",
            "unexpected_eof",
            "eof occurred",
            "connection reset",
            "connection aborted",
            "remote end closed",
            "temporarily unavailable",
            "ssl",
        )
    )


def _should_keep_current_usage(current, usage):
    """临时网络失败不覆盖已有成功额度。"""
    if not isinstance(current, dict) or current.get("error"):
        return False
    if not isinstance(usage, dict):
        return False
    error = usage.get("error")
    return isinstance(error, str) and _is_transient_usage_error(error)


def _is_transient_usage_error(message):
    lowered = message.lower()
    return "超时" in message or _is_transient_network_error(lowered)


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


@contextlib.contextmanager
def _file_lock(lock_path, timeout_seconds=30):
    """用独占锁文件串行化跨进程读写，避免后台刷新覆盖手动刷新。"""
    lock_path = Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    deadline = time.time() + timeout_seconds
    file_handle = None
    while True:
        try:
            file_handle = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(file_handle, str(os.getpid()).encode("utf-8"))
            break
        except FileExistsError:
            if time.time() >= deadline:
                raise TimeoutError(f"等待文件锁超时：{lock_path}")
            time.sleep(0.08)
    try:
        yield
    finally:
        if file_handle is not None:
            os.close(file_handle)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass
