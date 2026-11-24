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
from core.profile_service import get_active_auth_path

CHATGPT_BASE = "https://chatgpt.com/backend-api/codex"
API_BASE = "https://api.openai.com/v1"


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


def read_accounts(policies):
    if not DB_PATH.is_file():
        return []
    with closing(sqlite3.connect(DB_PATH.as_uri() + "?mode=ro", uri=True)) as db:
        setting = db.execute("SELECT value_json FROM settings WHERE key='profile_root'").fetchone()
        root = Path(json.loads(setting[0])) if setting else DEFAULT_PROFILE_ROOT
        rows = db.execute(
            "SELECT p.id,p.display_name,p.dir_name,u.payload_json FROM profiles p "
            "LEFT JOIN profile_usage u ON u.profile_id=p.id ORDER BY p.sort_order,p.display_name"
        ).fetchall()
    active = _auth(get_active_auth_path())
    accounts, identities = [], set()
    for pid, name, directory, usage in rows:
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
                account.identity = chatgpt_account_scope(values) or json.dumps(
                    (identity[0], hashlib.sha256(token.encode()).hexdigest())
                )
                if (jwt_expiration(token) or 0) <= time.time() + 10:
                    account.token_expired = True
                    raise ValueError("令牌已过期，请在账号管理刷新额度或重新授权")
                account.headers["ChatGPT-Account-Id"] = values["accountId"]
                cached = json.loads(usage or "{}")
                window = cached.get("oneWeek") or {}
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
    return accounts


class CapacityError(Exception):
    pass


class Scheduler:
    """All reservations and queue operations run on the gateway's event loop."""

    def __init__(self, accounts):
        self.accounts = accounts
        self.active = Counter()
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

    def eligible(self, account):
        return account.enabled and not account.reason and self.cooldown_until(account) <= time.monotonic()

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
        self.quota_restored_at[key] = max(self.quota_restored_at.get(key, 0), restored_at)
        if key in self.quota_cooldowns:
            self.quota_cooldowns[key] = {
                start: until for start, until in self.quota_cooldowns[key].items() if start > restored_at
            }
        self.changed.set()

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
                online = [a for a in self.accounts() if self.eligible(a)]

                def supports(account, requested):
                    return (not requested or not account.deployment or account.deployment == requested) and (
                        self.unsupported.get((account.id, requested), 0) <= time.monotonic()
                    )

                candidates = [a for a in online if supports(a, model)]
                if not candidates:
                    raise CapacityError("没有符合条件的可用账号")
                available = [a for a in candidates if self.active[a.id] < a.cap]

                def ready(oid, available_accounts=online):
                    head, authorize, requested = self.waiters[oid][0]
                    owner_now = current if head is ticket else authorize()
                    if not owner_now:
                        return False
                    cap = owner_now["cap"]
                    return (cap is None or self.owner_active[oid] < Decimal(cap)) and any(
                        self.active[a.id] < a.cap and supports(a, requested) for a in available_accounts
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
                    self.owner_active[owner_id] += 1
                    self.last[selected.id] = time.monotonic_ns()
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
            elif entry in queue:
                queue.remove(entry)
                if not queue:
                    del self.waiters[owner_id]
                    self.order.remove(owner_id)
            self.changed.set()
