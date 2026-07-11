import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge.commands import _get_profile_dir, _get_shared_app_root, rename_profile
from core import db
from core.app_server_service import find_codex_cli_path
from core.constants import PORTABLE_APP_DIR_NAME
from core.config_store import load_config
from core.profile_service import sync_codex_home_to_profile


class ProfileStorageTest(unittest.TestCase):
    def test_shared_client_is_outside_account_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_dir = root / "profile-id"
            shared_cli = root / ".shared" / PORTABLE_APP_DIR_NAME / "resources" / "codex.exe"
            shared_cli.parent.mkdir(parents=True)
            shared_cli.write_bytes(b"cli")

            self.assertEqual(_get_shared_app_root({"profile_root": str(root)}), root / ".shared")
            with (
                patch.dict("os.environ", {"LOCALAPPDATA": str(root / "empty")}, clear=False),
                patch("core.app_server_service.shutil.which", return_value=None),
            ):
                self.assertEqual(find_codex_cli_path(profile_dir), shared_cli)

    def test_runtime_auth_syncs_into_the_single_persistent_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            profile_dir = Path(temp_dir) / "profile"
            runtime_dir = profile_dir / "CodexHome"
            runtime_dir.mkdir(parents=True)
            (profile_dir / "auth.json").write_text('{"version":1}', encoding="utf-8")
            (runtime_dir / "auth.json").write_text('{"version":2}', encoding="utf-8")

            sync_codex_home_to_profile(profile_dir)

            self.assertEqual(
                (profile_dir / "auth.json").read_text(encoding="utf-8"),
                '{\n  "version": 2\n}',
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
