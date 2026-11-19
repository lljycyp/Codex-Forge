import asyncio
import hashlib
import json
import sqlite3
import time
import tomllib
from collections import Counter, defaultdict, deque
from contextlib import asynccontextmanager, closing
from dataclasses import dataclass, field
from pathlib import Path

from core.auth_service import auth_kind, extract_auth, is_newer_auth, jwt_expiration
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
                if (
                    conf.get("model_provider", "openai") != "openai"
                    or str(conf.get("openai_base_url") or API_BASE).rstrip("/") != API_BASE
                ):
                    raise ValueError("自定义 API 提供方未参与官方接口调度")
                token = auth["OPENAI_API_KEY"]
                identity = hashlib.sha256(token.encode()).hexdigest()
                account.base = API_BASE
            else:
                values = extract_auth(auth)
                token = values["accessToken"]
                if (jwt_expiration(token) or 0) <= time.time() + 10:
                    raise ValueError("令牌已过期，请在账号管理刷新额度或重新授权")
                identity = (values["accountId"], values["claims"].get("sub") or values["email"])
                account.headers["ChatGPT-Account-Id"] = values["accountId"]
                cached = json.loads(usage or "{}")
                window = cached.get("oneWeek") or {}
                if (
                    window.get("remainingPercent") == 0
                    and (window.get("resetAt") or 0) > time.time()
                    or cached.get("spendControlReached")
                    and (cached.get("fetchedAt") or 0) > time.time() - 300
                ):
                    raise ValueError("当前额度已用完")
            if enabled and identity in identities:
                raise ValueError("重复的登录身份")
            if enabled:
                identities.add(identity)
            account.headers["Authorization"] = "Bearer " + token
        except (ValueError, OSError, KeyError) as exc:
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
        self.unsupported = {}
        self.waiters = defaultdict(deque)
        self.order = deque()
        self.changed = asyncio.Event()
        self.accepting = False

    def eligible(self, account):
        return account.enabled and not account.reason and self.cooldown.get(account.id, 0) <= time.monotonic()

    def mark_unsupported(self, aid, model):
        if model:
            self.unsupported[(aid, model)] = time.monotonic() + 600

    @property
    def waiting(self):
        return sum(map(len, self.waiters.values()))

    def rejected(self, aid, status, delay):
        if status in (401, 403, 429) or status >= 500:
            self.cooldown[aid] = time.monotonic() + min(86400, max(1, delay))
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
        entry = (ticket, owner["cap"], model)
        queue.append(entry)
        selected = None
        deadline = time.monotonic() + 25
        try:
            while True:
                if not self.accepting or not authenticate():
                    raise CapacityError("服务已关闭或凭证已失效")
                online = [a for a in self.accounts() if self.eligible(a)]

                def supports(account, requested):
                    return self.unsupported.get((account.id, requested), 0) <= time.monotonic()

                candidates = [a for a in online if supports(a, model)]
                if not candidates:
                    raise CapacityError("没有符合条件的可用账号")
                available = [a for a in candidates if self.active[a.id] < a.cap]

                def ready(oid, available_accounts=online):
                    _, cap, requested = self.waiters[oid][0]
                    return self.owner_active[oid] < cap and any(
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
