import tempfile
import unittest
from pathlib import Path

import core.config_store as config_store


class ConfigStoreTest(unittest.TestCase):
    def test_config_round_trips_through_sqlite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_db_path = config_store.db.DB_PATH
            config_store.db.DB_PATH = Path(temp_dir) / "codex_forge.db"
            try:
                config = config_store.default_config()
                config.update(
                    {
                        "profile_root": "D:/CodexProfiles",
                        "profiles": ["a", "b"],
                        "active_profile": "b",
                        "launch_mode": "multi",
                    }
                )

                config_store.save_config(config)
                loaded = config_store.load_config()

                self.assertEqual(loaded["profiles"], ["a", "b"])
                self.assertEqual(loaded["active_profile"], "b")
                self.assertEqual(loaded["launch_mode"], "multi")
            finally:
                config_store.db.DB_PATH = original_db_path


if __name__ == "__main__":
    unittest.main()
