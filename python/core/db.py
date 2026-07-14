import contextlib
import json
import sqlite3
import time
import uuid

from core.constants import DB_PATH


@contextlib.contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    init_db(connection)
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db(connection):
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
          key TEXT PRIMARY KEY,
          value_json TEXT NOT NULL,
          updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS profiles (
          id TEXT PRIMARY KEY,
          display_name TEXT NOT NULL UNIQUE,
          dir_name TEXT NOT NULL UNIQUE,
          sort_order INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS profile_usage (
          profile_id TEXT PRIMARY KEY,
          payload_json TEXT NOT NULL,
          fetched_at REAL,
          updated_at INTEGER NOT NULL,
          FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS profile_usage_history (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          profile_id TEXT NOT NULL,
          payload_json TEXT NOT NULL,
          fetched_at REAL NOT NULL,
          created_at INTEGER NOT NULL,
          FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_profile_usage_history_profile_time
          ON profile_usage_history(profile_id, fetched_at DESC);

        CREATE TABLE IF NOT EXISTS profile_launch_settings (
          profile_id TEXT PRIMARY KEY,
          payload_json TEXT NOT NULL,
          updated_at INTEGER NOT NULL,
          FOREIGN KEY (profile_id) REFERENCES profiles(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS instruction_templates (
          scope_key TEXT NOT NULL,
          id TEXT NOT NULL,
          title TEXT NOT NULL,
          filename TEXT NOT NULL,
          sort_order INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL,
          PRIMARY KEY (scope_key, id),
          UNIQUE (scope_key, filename)
        );
        """
    )

def load_config(defaults):
    with connect() as connection:
        settings = {
            row["key"]: json.loads(row["value_json"])
            for row in connection.execute("SELECT key, value_json FROM settings")
        }
        profiles = [
            row["display_name"]
            for row in connection.execute("SELECT display_name FROM profiles ORDER BY sort_order, display_name")
        ]
    return {**defaults, **settings, "profiles": profiles}


def save_config(config):
    now = int(time.time())
    profiles = list(config.get("profiles", []))
    with connect() as connection:
        for key, value in config.items():
            if key == "profiles":
                continue
            connection.execute(
                """
                INSERT INTO settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                  value_json = excluded.value_json,
                  updated_at = excluded.updated_at
                """,
                (key, json.dumps(value, ensure_ascii=False), now),
            )

        for sort_order, name in enumerate(profiles):
            profile_id = uuid.uuid4().hex
            connection.execute(
                """
                INSERT INTO profiles (id, display_name, dir_name, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(display_name) DO UPDATE SET
                  sort_order = excluded.sort_order,
                  updated_at = excluded.updated_at
                """,
                (profile_id, name, profile_id, sort_order, now, now),
            )

        if profiles:
            placeholders = ",".join("?" for _ in profiles)
            connection.execute(
                f"DELETE FROM profiles WHERE display_name NOT IN ({placeholders})",
                profiles,
            )
        else:
            connection.execute("DELETE FROM profiles")


def load_usage_cache():
    with connect() as connection:
        return {
            row["display_name"]: json.loads(row["payload_json"])
            for row in connection.execute(
                "SELECT p.display_name, u.payload_json FROM profile_usage u JOIN profiles p ON p.id = u.profile_id"
            )
        }


def save_usage_cache(cache):
    now = int(time.time())
    with connect() as connection:
        for profile_name, usage in cache.items():
            profile = connection.execute(
                "SELECT id FROM profiles WHERE display_name = ?", (profile_name,)
            ).fetchone()
            if not profile:
                continue
            fetched_at = usage.get("fetchedAt") if isinstance(usage, dict) else None
            connection.execute(
                """
                INSERT INTO profile_usage (profile_id, payload_json, fetched_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_id) DO UPDATE SET
                  payload_json = excluded.payload_json,
                  fetched_at = excluded.fetched_at,
                  updated_at = excluded.updated_at
                """,
                (profile["id"], json.dumps(usage, ensure_ascii=False), fetched_at, now),
            )
            if isinstance(fetched_at, (int, float)) and not usage.get("error"):
                previous = connection.execute(
                    "SELECT fetched_at FROM profile_usage_history WHERE profile_id = ? ORDER BY fetched_at DESC LIMIT 1",
                    (profile["id"],),
                ).fetchone()
                if not previous or float(previous["fetched_at"]) != float(fetched_at):
                    connection.execute(
                        """
                        INSERT INTO profile_usage_history (profile_id, payload_json, fetched_at, created_at)
                        VALUES (?, ?, ?, ?)
                        """,
                        (profile["id"], json.dumps(usage, ensure_ascii=False), fetched_at, now),
                    )

        names = list(cache)
        if names:
            placeholders = ",".join("?" for _ in names)
            connection.execute(
                f"DELETE FROM profile_usage WHERE profile_id NOT IN (SELECT id FROM profiles WHERE display_name IN ({placeholders}))",
                names,
            )
        else:
            connection.execute("DELETE FROM profile_usage")
        connection.execute(
            "DELETE FROM profile_usage_history WHERE fetched_at < ?",
            (time.time() - 30 * 24 * 60 * 60,),
        )


def load_usage_history(profile_name, days=7, limit=500):
    cutoff = time.time() - max(1, min(int(days), 30)) * 24 * 60 * 60
    with connect() as connection:
        rows = connection.execute(
            """
            SELECT h.payload_json
            FROM profile_usage_history h
            JOIN profiles p ON p.id = h.profile_id
            WHERE p.display_name = ? AND h.fetched_at >= ?
            ORDER BY h.fetched_at DESC
            LIMIT ?
            """,
            (profile_name, cutoff, max(1, min(int(limit), 2000))),
        )
        return [json.loads(row["payload_json"]) for row in reversed(list(rows))]


def load_profile_launch_settings(profile_name):
    with connect() as connection:
        row = connection.execute(
            """
            SELECT s.payload_json
            FROM profile_launch_settings s
            JOIN profiles p ON p.id = s.profile_id
            WHERE p.display_name = ?
            """,
            (profile_name,),
        ).fetchone()
        return json.loads(row["payload_json"]) if row else {}


def save_profile_launch_settings(profile_name, payload):
    now = int(time.time())
    with connect() as connection:
        profile = connection.execute(
            "SELECT id FROM profiles WHERE display_name = ?", (profile_name,)
        ).fetchone()
        if not profile:
            raise ValueError("账号不存在")
        connection.execute(
            """
            INSERT INTO profile_launch_settings (profile_id, payload_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(profile_id) DO UPDATE SET
              payload_json = excluded.payload_json,
              updated_at = excluded.updated_at
            """,
            (profile["id"], json.dumps(payload, ensure_ascii=False), now),
        )


def get_profile(profile_name):
    with connect() as connection:
        row = connection.execute(
            "SELECT id, display_name, dir_name FROM profiles WHERE display_name = ?",
            (profile_name,),
        ).fetchone()
        return dict(row) if row else None


def list_profile_records():
    with connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                "SELECT id, display_name, dir_name FROM profiles ORDER BY sort_order, display_name"
            )
        ]


def rename_profile(old_name, new_name):
    with connect() as connection:
        cursor = connection.execute(
            "UPDATE profiles SET display_name = ?, updated_at = ? WHERE display_name = ?",
            (new_name, int(time.time()), old_name),
        )
        if cursor.rowcount != 1:
            raise ValueError("账号不存在")


def load_instruction_templates(scope_key):
    with connect() as connection:
        return [
            {"id": row["id"], "title": row["title"], "filename": row["filename"]}
            for row in connection.execute(
                """
                SELECT id, title, filename
                FROM instruction_templates
                WHERE scope_key = ?
                ORDER BY sort_order, title
                """,
                (scope_key,),
            )
        ]


def save_instruction_templates(scope_key, templates):
    now = int(time.time())
    with connect() as connection:
        connection.execute("DELETE FROM instruction_templates WHERE scope_key = ?", (scope_key,))
        for sort_order, template in enumerate(templates):
            connection.execute(
                """
                INSERT INTO instruction_templates
                  (scope_key, id, title, filename, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    scope_key,
                    template["id"],
                    template["title"],
                    template["filename"],
                    sort_order,
                    now,
                    now,
                ),
            )
