import asyncio
import hashlib
import json
import re
import sqlite3
import time
import tomllib
from collections import Counter, defaultdict, deque
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

from core.auth_service import auth_kind, chatgpt_account_scope, extract_auth, is_newer_auth, jwt_expiration
from core.constants import DB_PATH, DEFAULT_PROFILE_ROOT
from core.logger import get_logger
from core.profile_service import get_active_auth_path, profile_auth_lock, sync_auth_file
from core.usage_service import refresh_profile_usage

CHATGPT_BASE = "https://chatgpt.com/backend-api/codex"
API_BASE = "https://api.openai.com/v1"
PAUSE_WEEKLY_AT = 1
SERIAL_WEEKLY_AT = 2

logger = get_logger(__name__)


@dataclass
class Account:
    id: str
    name: str
    cap: int
    enabled: bool
    reason: str = ""
    base: str = CHATGPT_BASE
    headers: dict = field(default_factory=dict, repr=False)
    identity: str = field(default="", repr=False)
    deployment: str = ""
    spillover: str = ""
    quota_reset: float = 0
    token_expired: bool = False
    profile_dir: Path | None = None
    weekly_remaining: float | None = None
    weekly_checked_at: float = 0

    @property
    def quota_key(self) -> str:
        return self.identity or self.id

    @property
    def weekly_paused(self) -> bool:
        return self.weekly_remaining is not None and self.weekly_remaining <= PAUSE_WEEKLY_AT

    @property
    def weekly_limited(self) -> bool:
        return self.weekly_remaining is not None and self.weekly_remaining <= SERIAL_WEEKLY_AT


AZURE_V1 = re.compile(r"https://[a-zA-Z0-9-]+\.(?:openai\.azure\.com|services\.ai\.azure\.com)/openai/v1/?")
DEPLOYMENT = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}")


def configure_api(account, conf):
    provider = conf.get("model_provider", "openai")
    if provider == "openai":
        url = str(conf.get("openai_base_url") or API_BASE)
    else:
        config = conf.get("model_providers", {}).get(provider, {})
        url = str(config.get("base_url", ""))
    if provider == "openai" and url.rstrip("/") == API_BASE:
        account.base = API_BASE
        return
    if not AZURE_V1.fullmatch(url):
        raise ValueError("该 API 提供方未参与调度")
    options = conf.get("model_providers", {}).get(provider, {})
    headers = {str(k).lower(): v for k, v in options.get("http_headers", {}).items()}
    primary, backup = conf.get("model", ""), headers.get("x-ms-spillover-deployment", "")
    if not isinstance(primary, str) or not DEPLOYMENT.fullmatch(primary):
        raise ValueError("请在账号的 TOML 中填写 Azure 主部署名 model")
    if backup and (not isinstance(backup, str) or not DEPLOYMENT.fullmatch(backup) or backup == primary):
        raise ValueError("Azure 备用部署名称无效或与主部署相同")
    account.base, account.deployment, account.spillover = url.rstrip("/"), primary, backup


def _auth(path):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (ValueError, OSError):
        return {}


def _chatgpt_identity(values):
    if scope := chatgpt_account_scope(values):
        return scope
    user = hashlib.sha256(values["accessToken"].encode()).hexdigest()
    return hashlib.sha256(json.dumps((values["accountId"], user)).encode()).hexdigest()


def _weekly_reading(usage):
    if not isinstance(usage, dict) or usage.get("error"):
        return None
    window = usage.get("oneWeek")
    remaining = window.get("remainingPercent") if isinstance(window, dict) else None
    if not isinstance(remaining, (int, float)) or isinstance(remaining, bool) or not 0 <= remaining <= 100:
        return None
    checked_at = usage.get("queryStartedAt", usage.get("fetchedAt"))
    if not isinstance(checked_at, (int, float)) or not 0 < checked_at < float("inf"):
        checked_at = 0
    return checked_at, remaining


def refresh_weekly_quota(account):
    folder = account.profile_dir
    if folder is None or not (auth_path := folder / "auth.json").is_file():
        return
    with profile_auth_lock(folder):
        if _chatgpt_identity(extract_auth(_auth(auth_path))) != account.identity:
            return
        sync_auth_file(get_active_auth_path(), auth_path)
        refresh_profile_usage(account.name, folder, profile_id=account.id)


def read_accounts(policies):
    if not DB_PATH.is_file():
        return []
    with closing(sqlite3.connect(DB_PATH.as_uri() + "?mode=ro", uri=True)) as db:
        setting = db.execute("SELECT value_json FROM settings WHERE key='profile_root'").fetchone()
        root = Path(json.loads(setting[0])) if setting else DEFAULT_PROFILE_ROOT
        rows = db.execute(
            """
            SELECT p.id,p.display_name,p.dir_name,u.payload_json,
                (SELECT h.payload_json FROM profile_usage_history h WHERE h.profile_id=p.id
                    AND CASE WHEN json_valid(h.payload_json)
                        THEN json_type(h.payload_json, '$.oneWeek.remainingPercent') END IN ('integer', 'real')
                    ORDER BY h.fetched_at DESC, h.id DESC LIMIT 1)
            FROM profiles p LEFT JOIN profile_usage u ON u.profile_id=p.id ORDER BY p.sort_order,p.display_name
            """
        ).fetchall()
    active = _auth(get_active_auth_path())
    accounts, identities = [], set()
    weekly = {}
    for pid, name, directory, usage, last_weekly_usage in rows:
        enabled, cap = policies.get(pid, (True, 2))
        account = Account(pid, name, cap, enabled)
        accounts.append(account)
        folder = root / directory
        try:
            auth = _auth(folder / "auth.json")
            for candidate in (_auth(folder / "CodexHome/auth.json"), active):
                if is_newer_auth(candidate, auth):
                    auth = candidate
            if auth_kind(auth) == "api":
                config_path = folder / "CodexHome/config.toml"
                conf = tomllib.loads(config_path.read_text("utf-8-sig")) if config_path.exists() else {}
                configure_api(account, conf)
                token = auth["OPENAI_API_KEY"]
                identity = hashlib.sha256(token.encode()).hexdigest()
                account.identity = identity
            else:
                values = extract_auth(auth)
                token = values["accessToken"]
                identity = (values["accountId"], values["claims"].get("sub") or values["email"])
                account.identity = _chatgpt_identity(values)
                account.profile_dir = folder
                cached = json.loads(usage or "{}")
                window = cached.get("oneWeek") or {}
                reading = _weekly_reading(cached) or _weekly_reading(json.loads(last_weekly_usage or "{}"))
                if reading:
                    checked_at, remaining = reading
                    previous_time, previous_remaining = weekly.get(account.identity, (-1, 0))
                    if checked_at > previous_time or (checked_at == previous_time and remaining < previous_remaining):
                        weekly[account.identity] = reading
                if (jwt_expiration(token) or 0) <= time.time() + 10:
                    account.token_expired = True
                    raise ValueError("令牌已过期，请在账号管理刷新额度或重新授权")
                account.headers["ChatGPT-Account-Id"] = values["accountId"]
                reset = (window.get("resetAt") or 0) if window.get("remainingPercent") == 0 else 0
                if cached.get("spendControlReached"):
                    reset = max(reset, (cached.get("fetchedAt") or 0) + 300)
                if reset > time.time():
                    account.quota_reset = reset
                    raise ValueError("当前额度已用完")
            if enabled and identity in identities:
                raise ValueError("重复的登录身份")
            if enabled:
                identities.add(identity)
            account.headers["Authorization"] = "Bearer " + token
        except (ValueError, OSError, KeyError, TypeError, AttributeError) as exc:
            account.reason = str(exc)
    for account in accounts:
        if account.identity in weekly:
            account.weekly_checked_at, account.weekly_remaining = weekly[account.identity]
    return accounts


class CapacityError(Exception):
    pass


class Scheduler:
    """All reservations and queue operations run on the gateway's event loop."""

    def __init__(self, accounts, store, refresh_usage):
        self.accounts = accounts
        self.store = store
        self.refresh_usage = refresh_usage
        self.active = Counter()
        self.identity_active = Counter()
        self.owner_active = Counter()
        self.last = Counter()
        self.cooldown = {}
        self.quota_cooldowns: dict[tuple[str, str], dict[float, float]] = {}
        self.quota_restored_at: dict[tuple[str, str], float] = {}
        self.unsupported = {}
        self.waiters = defaultdict(deque)
        self.order = deque()
        self.changed = asyncio.Event()
        self.accepting = False
        started_at = time.time()
        self.weekly_recheck_after = {
            key: started_at if since is None else since
            for key, since in store.option("weeklyRecheckAfter", {}).items()
        }

    def eligible(self, account):
        return (
            account.enabled and not account.reason and not account.weekly_paused
            and self.cooldown_until(account) <= time.monotonic()
        )

    def cooldown_until(self, account):
        quota = self.quota_cooldowns.get((account.id, account.identity), {})
        return max(self.cooldown.get(account.id, 0), max(quota.values(), default=0))

    def quota_rejected(self, account, delay, started_at):
        key = (account.id, account.identity)
        # A request sent before a successful reset can report its old limit afterward.
        if started_at <= self.quota_restored_at.get(key, 0):
            return
        now = time.monotonic()
        limits = {start: until for start, until in self.quota_cooldowns.get(key, {}).items() if until > now}
        limits[started_at] = max(limits.get(started_at, 0), now + max(1, delay))
        self.quota_cooldowns[key] = limits
        self.changed.set()

    def quota_restored(self, aid, identity, restored_at):
        key = (aid, identity)
        if restored_at <= self.quota_restored_at.get(key, 0):
            return
        self.quota_restored_at[key] = restored_at
        if key in self.quota_cooldowns:
            self.quota_cooldowns[key] = {
                start: until for start, until in self.quota_cooldowns[key].items() if start > restored_at
            }
        self.changed.set()
        if identity in self.weekly_recheck_after:
            restored = any(
                (account.id, account.identity) == key and (account.weekly_remaining or 0) > SERIAL_WEEKLY_AT
                for account in self.accounts()
            )
            if restored and identity in self.weekly_recheck_after:
                del self.weekly_recheck_after[identity]
                self._save_weekly_checks()

    def update_weekly_checks(self, accounts):
        changed = False
        for account in accounts:
            key = account.quota_key
            since = self.weekly_recheck_after.get(key, 0)
            if account.weekly_limited and self.identity_active[key] and since is not None:
                self.weekly_recheck_after[key] = None
                changed = True
            elif since and account.weekly_checked_at > since:
                del self.weekly_recheck_after[key]
                changed = True
        if changed:
            self._save_weekly_checks()

    def _save_weekly_checks(self):
        try:
            self.store.set_option("weeklyRecheckAfter", self.weekly_recheck_after)
        except sqlite3.Error as exc:
            logger.warning("周额度复查状态保存失败 错误类型=%s", type(exc).__name__)

    def weekly_reason(self, account):
        if account.enabled:
            if account.weekly_paused:
                return "周额度剩余 ≤ 1%，已暂停派发"
            if self.weekly_recheck_after.get(account.quota_key) is not None:
                return "等待复查周额度"
            if account.weekly_limited or account.quota_key in self.weekly_recheck_after:
                return "周额度保护中，限单并发"
        return ""

    def _has_capacity(self, account):
        if account.quota_key in self.weekly_recheck_after:
            return False
        if account.weekly_limited:
            return self.identity_active[account.quota_key] == 0
        return self.active[account.id] < account.cap

    def mark_unsupported(self, aid, model):
        if model:
            self.unsupported[(aid, model)] = time.monotonic() + 600

    @property
    def waiting(self):
        return sum(map(len, self.waiters.values()))

    def rejected(self, aid, status, delay):
        if status in (401, 403, 429) or status >= 500:
            self.cooldown[aid] = max(self.cooldown.get(aid, 0), time.monotonic() + max(1, delay))
            self.changed.set()

    @asynccontextmanager
    async def reserve(self, owner, authenticate, model=None):
        ticket = object()
        owner_id = owner["id"]
        if self.waiting >= 64 or len(self.waiters.get(owner_id, ())) >= 12:
            raise CapacityError("队列已满")
        queue = self.waiters[owner_id]
        if not queue:
            self.order.append(owner_id)
        entry = (ticket, authenticate, model)
        queue.append(entry)
        selected = None
        deadline = time.monotonic() + 25
        try:
            while True:
                if not self.accepting or not (current := authenticate()):
                    raise CapacityError("服务已关闭或凭证已失效")
                accounts = self.accounts()
                online = [a for a in accounts if self.eligible(a)]

                def supports(account, requested):
                    return (not requested or not account.deployment or account.deployment == requested) and (
                        self.unsupported.get((account.id, requested), 0) <= time.monotonic()
                    )

                candidates = [a for a in online if supports(a, model)]
                if not candidates:
                    if any(a.enabled and a.weekly_paused and supports(a, model) for a in accounts):
                        raise CapacityError("周额度不足，等待账号额度恢复")
                    raise CapacityError("没有符合条件的可用账号")
                available = [a for a in candidates if self._has_capacity(a)]

                def ready(oid, available_accounts=online):
                    head, authorize, requested = self.waiters[oid][0]
                    owner_now = current if head is ticket else authorize()
                    if not owner_now:
                        return False
                    cap = owner_now["cap"]
                    return (cap is None or self.owner_active[oid] < Decimal(cap)) and any(
                        self._has_capacity(a) and supports(a, requested) for a in available_accounts
                    )

                next_owner = next((oid for oid in self.order if ready(oid)), None)
                if available and next_owner == owner_id and queue[0][0] is ticket:
                    selected = min(available, key=lambda a: (self.active[a.id] / a.cap, self.last[a.id]))
                    queue.popleft()
                    self.order.remove(owner_id)
                    if queue:
                        self.order.append(owner_id)
                    else:
                        del self.waiters[owner_id]
                    self.active[selected.id] += 1
                    self.identity_active[selected.quota_key] += 1
                    self.owner_active[owner_id] += 1
                    self.last[selected.id] = time.monotonic_ns()
                    if selected.weekly_limited:
                        self.weekly_recheck_after[selected.quota_key] = None
                        self._save_weekly_checks()
                    self.changed.set()
                    break
                if time.monotonic() >= deadline:
                    raise CapacityError("等待可用账号超时")
                self.changed.clear()
                try:
                    await asyncio.wait_for(self.changed.wait(), 1)
                except TimeoutError:
                    pass
            yield selected
        finally:
            if selected:
                self.active[selected.id] -= 1
                self.owner_active[owner_id] -= 1
                key = selected.quota_key
                self.identity_active[key] -= 1
                if not self.identity_active[key] and self.weekly_recheck_after.get(key, 0) is None:
                    # Only a quota read started after the last request finished may release this account.
                    self.weekly_recheck_after[key] = time.time()
                    self._save_weekly_checks()
                    if self.accepting:
                        self.refresh_usage(selected)
            elif entry in queue:
                queue.remove(entry)
                if not queue:
                    del self.waiters[owner_id]
                    self.order.remove(owner_id)
            self.changed.set()
