"""Local gateway credentials and owner-scoped replay data. Account credentials stay in Forge profiles."""

import base64
import hashlib
import json
import secrets
import sqlite3
import time
import zlib
from pathlib import Path

from core.secure_store import protect_bytes, unprotect_bytes

MAX_RESOURCE = 24 * 1024 * 1024
OWNER_BUDGET = 96 * 1024 * 1024
TOTAL_BUDGET = 384 * 1024 * 1024


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def _encode_key_cap(value):
    if value is None:
        return 0
    if type(value) is int:
        value = str(value)
    if isinstance(value, str):
        digits = value.strip().lstrip("0")
        if digits.isascii() and digits.isdecimal():
            # Quote large values so SQLite's INTEGER affinity and JavaScript preserve every digit.
            return int(digits) if len(digits) <= 15 else json.dumps(digits)
    raise ValueError("请输入正整数或选择不限制")


def _read_key(row):
    key = dict(row)
    cap = key["cap"]
    key["cap"] = json.loads(cap) if isinstance(cap, str) else cap or None
    return key


class GatewayStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.directory / "gateway.sqlite", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS options(k TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS owners(id TEXT PRIMARY KEY, name TEXT NOT NULL,
                hash TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL, cap INTEGER NOT NULL,
                expires INTEGER NOT NULL, calls INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS policies(profile TEXT PRIMARY KEY, enabled INTEGER NOT NULL, cap INTEGER NOT NULL);
            CREATE TABLE IF NOT EXISTS objects(owner TEXT, id TEXT, data BLOB NOT NULL, expires INTEGER NOT NULL,
                PRIMARY KEY(owner,id));
            CREATE INDEX IF NOT EXISTS objects_expiry ON objects(expires);
        """)
        self.purge()

    def purge(self):
        self.db.execute("DELETE FROM objects WHERE expires<=?", (int(time.time()),))

    def option(self, name, default=None):
        row = self.db.execute("SELECT value FROM options WHERE k=?", (name,)).fetchone()
        return json.loads(row[0]) if row else default

    def set_option(self, name, value):
        self.db.execute("INSERT OR REPLACE INTO options VALUES (?,?)", (name, json.dumps(value)))

    def list_keys(self):
        return [
            _read_key(row)
            for row in self.db.execute("SELECT id,name,enabled,cap,expires,calls FROM owners ORDER BY rowid")
        ]

    def record_call(self, owner):
        if owner == "local":
            self.db.execute(
                "INSERT INTO options VALUES ('localCalls', '1') "
                "ON CONFLICT(k) DO UPDATE SET value=CAST(value AS INTEGER)+1"
            )
        else:
            self.db.execute("UPDATE owners SET calls=calls+1 WHERE id=?", (owner,))

    def change_key(self, action, payload):
        owner = str(payload.get("id", ""))
        if action != "create" and not self.db.execute("SELECT 1 FROM owners WHERE id=?", (owner,)).fetchone():
            raise ValueError("找不到这个 Key")
        if action in ("create", "rotate"):
            key = "fg_" + secrets.token_urlsafe(32)
            if action == "create":
                name = str(payload.get("name") or "").strip()
                cap, days = _encode_key_cap(payload.get("cap", 2)), int(payload.get("days", 0))
                if not name or len(name) > 64 or not 0 <= days <= 3650:
                    raise ValueError("请检查名称和有效天数")
                owner = secrets.token_hex(12)
                self.db.execute(
                    "INSERT INTO owners VALUES(?,?,?,1,?,?,0)",
                    (owner, name, digest(key), cap, int(time.time()) + days * 86400 if days else 0),
                )
            else:
                self.db.execute("UPDATE owners SET hash=? WHERE id=?", (digest(key), owner))
            return {"id": owner, "key": key}
        if action == "toggle":
            self.db.execute("UPDATE owners SET enabled=? WHERE id=?", (bool(payload["enabled"]), owner))
        elif action == "set_cap":
            self.db.execute("UPDATE owners SET cap=? WHERE id=?", (_encode_key_cap(payload["cap"]), owner))
        elif action == "revoke":
            self.db.execute("DELETE FROM owners WHERE id=?", (owner,))
            self.db.execute("DELETE FROM objects WHERE owner=?", (owner,))
        else:
            raise ValueError("未知 Key 操作")
        return {}

    def identify(self, key):
        row = self.db.execute(
            "SELECT id,name,cap FROM owners WHERE hash=? AND enabled AND (expires=0 OR expires>?)",
            (digest(key), int(time.time())),
        ).fetchone()
        return _read_key(row) if row else None

    def policies(self):
        return {
            r["profile"]: (bool(r["enabled"]), r["cap"]) for r in self.db.execute("SELECT * FROM policies")
        }

    def put(self, owner, rid, data):
        value = json.dumps(data, ensure_ascii=False, separators=(",", ":")).encode()
        if len(value) > MAX_RESOURCE:
            raise ValueError("会话或文件超出网关单项存储上限")
        blob = protect_bytes(b"Z" + zlib.compress(value, level=1))
        self.db.execute("BEGIN IMMEDIATE")
        with self.db:
            if owner != "local" and not self.db.execute("SELECT 1 FROM owners WHERE id=?", (owner,)).fetchone():
                raise ValueError("访问 Key 已撤销")
            self.purge()
            used, total = self.db.execute(
                """
                SELECT COALESCE(SUM(CASE WHEN owner=:owner THEN length(data) ELSE 0 END),0),
                       COALESCE(SUM(length(data)),0)
                FROM objects WHERE owner<>:owner OR id<>:rid
                """,
                {"owner": owner, "rid": rid},
            ).fetchone()
            bytes_needed = max(used + len(blob) - OWNER_BUDGET, total + len(blob) - TOTAL_BUDGET)
            if bytes_needed > 0:
                evictions = []
                if rid.startswith("response:"):
                    for old_id, size in self.db.execute(
                        """
                        SELECT id, length(data) FROM objects
                        WHERE owner=? AND id GLOB 'response:*' AND id<>?
                        ORDER BY expires, rowid
                        """,
                        (owner, rid),
                    ):
                        evictions.append((owner, old_id))
                        bytes_needed -= size
                        if bytes_needed <= 0:
                            break
                if bytes_needed > 0:
                    raise ValueError("网关临时存储已满，请稍后重试")
                self.db.executemany("DELETE FROM objects WHERE owner=? AND id=?", evictions)
            self.db.execute(
                "INSERT OR REPLACE INTO objects VALUES(?,?,?,?)", (owner, rid, blob, int(time.time()) + 86400)
            )

    def get(self, owner, rid):
        row = self.db.execute(
            "SELECT data FROM objects WHERE owner=? AND id=? AND expires>?", (owner, rid, int(time.time()))
        ).fetchone()
        if not row:
            raise ValueError("引用的资源不存在、已过期或属于其他使用者")
        value = unprotect_bytes(row[0])
        return json.loads(zlib.decompress(value[1:]) if value.startswith(b"Z") else value)

    def secret(self, name, create):
        value = self.option(name)
        if value:
            return unprotect_bytes(base64.b64decode(value))
        value = create()
        self.set_option(name, base64.b64encode(protect_bytes(value)).decode())
        return value
