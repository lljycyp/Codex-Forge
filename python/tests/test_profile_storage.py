import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge.commands import _get_profile_dir, _get_shared_app_root, delete_profile, get_runtime_status, rename_profile
from core import db
from core.app_server_service import find_codex_cli_path
from core.constants import PORTABLE_APP_DIR_NAME
from core.config_store import load_config, normalize_config
from core.profile_service import sync_codex_home_to_profile


class ProfileStorageTest(unittest.TestCase):
    def test_runtime_status_uses_one_process_snapshot(self):
        config = {"profiles": ["work"], "active_profile": "work", "launch_mode": "switch"}
        processes = [{"pid": 123, "command_line": "ChatGPT.exe"}]

        with (
            patch("bridge.commands.load_config", return_value=config),
            patch("bridge.commands.read_running_codex_processes", return_value=processes) as read_processes,
            patch("bridge.commands._get_current_login", return_value=("work", "chatgpt")),
        ):
            result = get_runtime_status()

        self.assertEqual(result, {
            "runningCount": 1, "balancedRunning": False, "balancedUsesSystemAuth": False, "activeProfile": "work",
            "systemAuthMode": "chatgpt", "profiles": {"work": True},
        })
        read_processes.assert_called_once_with()

        processes[0]["command_line"] += " --codex-forge-balanced --codex-forge-balanced-chatgpt"
        with (
            patch("bridge.commands.load_config", return_value=config),
            patch("bridge.commands.read_running_codex_processes", return_value=processes),
            patch("bridge.commands._get_current_login", return_value=("work", "chatgpt")),
        ):
            result = get_runtime_status()
        self.assertTrue(result["balancedRunning"])
        self.assertTrue(result["balancedUsesSystemAuth"])
        self.assertFalse(result["profiles"]["work"])

    def test_external_api_key_detaches_the_old_profile_without_stopping_codex(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(db, "DB_PATH", Path(temp_dir) / "forge.db"):
            root = Path(temp_dir)
            config = {"profiles": ["work"], "active_profile": "work", "launch_mode": "switch", "profile_root": temp_dir}
            db.save_config(config)
            stored = _get_profile_dir(config, "work") / "auth.json"
            stored.parent.mkdir()
            stored.write_text('{"OPENAI_API_KEY":"saved-test-key"}', encoding="utf-8")
            active = root / "system-auth.json"
            with (
                patch("bridge.commands.get_active_auth_path", return_value=active),
                patch("bridge.commands.read_running_codex_processes", return_value=[{"command_line": "ChatGPT.exe"}]),
                patch("bridge.commands.load_config", return_value=config),
            ):
                active.write_bytes(stored.read_bytes())
                self.assertTrue(get_runtime_status()["profiles"]["work"])
                active.write_text('{"OPENAI_API_KEY":"fg_external-test-key"}', encoding="utf-8")
                result = get_runtime_status()

            self.assertEqual(result, {
                "runningCount": 1, "balancedRunning": False, "balancedUsesSystemAuth": False, "activeProfile": "",
                "systemAuthMode": "api", "profiles": {"work": False},
            })
            self.assertEqual(db.load_config({})["active_profile"], "work")

    def test_codex_skin_is_disabled_for_existing_configs(self):
        self.assertFalse(normalize_config({})["codex_skin_enabled"])

    def test_legacy_launch_mode_is_ignored_without_changing_saved_accounts(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(db, "DB_PATH", Path(temp_dir) / "forge.db"):
            db.save_config({"profiles": ["work"], "active_profile": "work", "launch_mode": "multi"})
            config = load_config()
            self.assertNotIn("launch_mode", config)
            self.assertEqual(config["active_profile"], "work")
            self.assertEqual(config["profiles"], ["work"])

    def test_cannot_delete_account_with_running_legacy_client(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(db, "DB_PATH", Path(temp_dir) / "forge.db"):
            config = {"profiles": ["work"], "profile_root": temp_dir}
            db.save_config(config)
            profile_dir = _get_profile_dir(config, "work")
            profile_dir.mkdir()
            user_data = profile_dir / "AppData" / "Roaming" / "Codex" / "web" / "Codex"
            processes = [{"command_line": f'Codex.exe --user-data-dir="{user_data}"'}]
            with patch("core.codex_source.read_running_codex_processes", return_value=processes):
                with self.assertRaisesRegex(RuntimeError, "请先关闭 Codex"):
                    delete_profile({"name": "work"})
            self.assertTrue(profile_dir.is_dir())
            self.assertEqual(load_config()["profiles"], ["work"])

    def test_shared_client_is_outside_account_directories(self):
        for name in (PORTABLE_APP_DIR_NAME, "ChatGPTPortableApp"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                profile_dir = root / "profile-id"
                shared_cli = root / ".shared" / name / "resources" / "codex.exe"
                shared_cli.parent.mkdir(parents=True)
                shared_cli.write_bytes(b"cli")
                (shared_cli.parent.parent / "ChatGPT.exe").touch()

                self.assertEqual(_get_shared_app_root({"profile_root": str(root)}), root / ".shared")
                with (
                    patch.dict("os.environ", {"LOCALAPPDATA": str(root / "empty")}, clear=False),
                    patch("core.app_server_service.shutil.which", return_value=None),
                ):
                    self.assertEqual(find_codex_cli_path(profile_dir), shared_cli)

    def test_unidentified_runtime_auth_cannot_replace_persistent_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / "profile"
            runtime_dir = profile_dir / "CodexHome"
            runtime_dir.mkdir(parents=True)
            (profile_dir / "auth.json").write_text('{"version":1}', encoding="utf-8")
            (runtime_dir / "auth.json").write_text('{"version":2}', encoding="utf-8")

            sync_codex_home_to_profile(profile_dir)

            self.assertEqual(
                (profile_dir / "auth.json").read_text(encoding="utf-8"),
                '{"version":1}',
            )

    def test_profiles_use_immutable_ids_and_usage_foreign_keys(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "codex_forge.db"
            with patch.object(db, "DB_PATH", db_path):
                db.save_config({"profiles": ["work"]})
                db.save_usage_cache({"work": {"planType": "plus"}})
                config = db.load_config({"profiles": []})
                profile = db.get_profile("work")
                usage = db.load_usage_cache()

            self.assertEqual(config["profiles"], ["work"])
            self.assertIsNotNone(profile)
            assert profile is not None
            self.assertEqual(profile["id"], profile["dir_name"])
            self.assertNotEqual(profile["dir_name"], "work")
            self.assertEqual(usage["work"]["planType"], "plus")

    def test_rename_changes_display_name_without_moving_storage_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            db_path = root / "codex_forge.db"
            profile_root = root / "profiles"

            with patch.object(db, "DB_PATH", db_path):
                db.save_config({"profiles": ["work"], "profile_root": str(profile_root)})
                config = load_config()
                immutable_dir = _get_profile_dir(config, "work")
                immutable_dir.mkdir(parents=True)
                (immutable_dir / "auth.json").write_text("{}", encoding="utf-8")

                with patch("bridge.commands.read_running_codex_commands", return_value=""):
                    rename_profile({"oldName": "work", "newName": "renamed"})

                renamed = db.get_profile("renamed")
                self.assertIsNotNone(renamed)
                assert renamed is not None
                self.assertEqual(immutable_dir.name, renamed["dir_name"])
                self.assertTrue(immutable_dir.exists())


if __name__ == "__main__":
    unittest.main()
