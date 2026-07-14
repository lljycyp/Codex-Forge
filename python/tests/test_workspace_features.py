import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge.commands import _extract_toml_root, _remove_toml_root
from core import db
from core.secure_store import protect_bytes, unprotect_bytes
from core.workspace_service import (
    delete_mcp_server,
    install_skill,
    list_sessions,
    read_workspace,
    remove_skill,
    save_mcp_server,
)


class WorkspaceFeatureTests(unittest.TestCase):
    def test_usage_history_and_launch_settings_are_profile_scoped(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch("core.db.DB_PATH", Path(temp_dir) / "forge.db"):
            db.save_config({"profiles": ["work"]})
            now = time.time()
            db.save_usage_cache({"work": {"fetchedAt": now - 60, "oneWeek": {"remainingPercent": 80}, "error": None}})
            db.save_usage_cache({"work": {"fetchedAt": now, "oneWeek": {"remainingPercent": 70}, "error": None}})
            self.assertEqual([80, 70], [item["oneWeek"]["remainingPercent"] for item in db.load_usage_history("work", 30)])

            value = {"workingDir": temp_dir, "args": ["--test"], "env": {"HTTP_PROXY": "http://127.0.0.1:7890"}}
            db.save_profile_launch_settings("work", value)
            self.assertEqual(value, db.load_profile_launch_settings("work"))

    def test_mcp_crud_preserves_unrelated_toml(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text('model = "gpt-test"\n\n[features]\napps = true\n', encoding="utf-8")
            save_mcp_server(config_path, {"name": "demo", "command": "npx", "args": ["-y", "demo"], "env": {"TOKEN": "secret"}})
            workspace = read_workspace(temp_dir)
            self.assertEqual("demo", workspace["mcpServers"][0]["name"])
            self.assertIn('model = "gpt-test"', config_path.read_text(encoding="utf-8"))
            delete_mcp_server(config_path, "demo")
            self.assertNotIn("mcp_servers.demo", config_path.read_text(encoding="utf-8"))
            self.assertIn("[features]", config_path.read_text(encoding="utf-8"))

    def test_skill_remove_moves_to_backup(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source-skill"
            source.mkdir()
            (source / "SKILL.md").write_text("# Skill", encoding="utf-8")
            codex_home = root / "codex-home"
            installed = install_skill(codex_home, source)
            self.assertTrue(Path(installed["path"]).is_dir())
            removed = remove_skill(codex_home, "source-skill")
            self.assertTrue(Path(removed["backupPath"]).is_dir())

    def test_session_index_is_read_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            session = Path(temp_dir) / "sessions" / "2026" / "sample.jsonl"
            session.parent.mkdir(parents=True)
            session.write_text(
                "\n".join(
                    [
                        json.dumps({"type": "session_meta", "payload": {"id": "thread-1", "cwd": "D:\\Work"}}),
                        json.dumps({"type": "response_item", "payload": {"role": "user", "content": [{"type": "input_text", "text": "Fix startup bug"}]}}),
                    ]
                ),
                encoding="utf-8",
            )
            before = session.read_bytes()
            result = list_sessions(temp_dir)
            self.assertEqual("thread-1", result[0]["id"])
            self.assertEqual("Fix startup bug", result[0]["title"])
            self.assertEqual(before, session.read_bytes())

    def test_toml_root_selection(self):
        content = 'model = "a"\napproval = "ask"\n\n[mcp_servers.demo]\ncommand = "npx"\n\n[features]\napps = true\n'
        self.assertIn('model = "a"', _extract_toml_root(content, "model"))
        self.assertIn("[mcp_servers.demo]", _extract_toml_root(content, "mcp_servers"))
        self.assertNotIn("mcp_servers.demo", _remove_toml_root(content, "mcp_servers"))
        self.assertIn("[features]", _remove_toml_root(content, "mcp_servers"))

    @unittest.skipUnless(os.name == "nt", "DPAPI is Windows-only")
    def test_dpapi_round_trip(self):
        value = b"sensitive-backup"
        self.assertEqual(value, unprotect_bytes(protect_bytes(value)))


if __name__ == "__main__":
    unittest.main()
