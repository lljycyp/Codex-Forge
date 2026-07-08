import contextlib
import json
import sqlite3
import time

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
          name TEXT PRIMARY KEY,
          dir_name TEXT NOT NULL UNIQUE,
          sort_order INTEGER NOT NULL DEFAULT 0,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS profile_usage (
          profile_name TEXT PRIMARY KEY,
          payload_json TEXT NOT NULL,
          fetched_at REAL,
          updated_at INTEGER NOT NULL,
          FOREIGN KEY (profile_name) REFERENCES profiles(name)
            ON DELETE CASCADE ON UPDATE CASCADE
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
            row["name"]
            for row in connection.execute("SELECT name FROM profiles ORDER BY sort_order, name")
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
            connection.execute(
                """
                INSERT INTO profiles (name, dir_name, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(name) DO UPDATE SET
                  sort_order = excluded.sort_order,
                  updated_at = excluded.updated_at
                """,
                (name, name, sort_order, now, now),
            )

        if profiles:
            placeholders = ",".join("?" for _ in profiles)
            connection.execute(
                f"DELETE FROM profiles WHERE name NOT IN ({placeholders})",
                profiles,
            )
        else:
            connection.execute("DELETE FROM profiles")


def load_usage_cache():
    with connect() as connection:
        return {
            row["profile_name"]: json.loads(row["payload_json"])
            for row in connection.execute("SELECT profile_name, payload_json FROM profile_usage")
        }


def save_usage_cache(cache):
    now = int(time.time())
    with connect() as connection:
        for profile_name, usage in cache.items():
            connection.execute(
                """
                INSERT INTO profiles (name, dir_name, sort_order, created_at, updated_at)
                VALUES (?, ?, 0, ?, ?)
                ON CONFLICT(name) DO NOTHING
                """,
                (profile_name, profile_name, now, now),
            )
            fetched_at = usage.get("fetchedAt") if isinstance(usage, dict) else None
            connection.execute(
                """
                INSERT INTO profile_usage (profile_name, payload_json, fetched_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(profile_name) DO UPDATE SET
                  payload_json = excluded.payload_json,
                  fetched_at = excluded.fetched_at,
                  updated_at = excluded.updated_at
                """,
                (profile_name, json.dumps(usage, ensure_ascii=False), fetched_at, now),
            )

        names = list(cache)
        if names:
            placeholders = ",".join("?" for _ in names)
            connection.execute(
                f"DELETE FROM profile_usage WHERE profile_name NOT IN ({placeholders})",
                names,
            )
        else:
            connection.execute("DELETE FROM profile_usage")


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
