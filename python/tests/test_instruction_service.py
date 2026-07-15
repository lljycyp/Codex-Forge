import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import db
from core.instruction_service import BUILTIN_TEMPLATES, list_instruction_templates


class InstructionServiceTests(unittest.TestCase):
    def test_builtin_templates_are_created_disabled_and_only_once(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch("core.db.DB_PATH", Path(temp_dir) / "forge.db"):
            root = Path(temp_dir)
            payload = {
                "templateDir": str(root / "templates"),
                "configPath": str(root / "config.toml"),
            }

            first = list_instruction_templates(payload)
            second = list_instruction_templates(payload)

            self.assertEqual([item["filename"] for item in BUILTIN_TEMPLATES], [item["filename"] for item in first["templates"]])
            self.assertTrue(all(not item["enabled"] for item in first["templates"]))
            self.assertEqual("", first["currentInstructionFile"])
            self.assertEqual(2, len(second["templates"]))
            self.assertFalse(Path(payload["configPath"]).exists())
            for template in BUILTIN_TEMPLATES:
                self.assertTrue((Path(payload["templateDir"]) / template["filename"]).is_file())

    def test_existing_same_name_template_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch("core.db.DB_PATH", Path(temp_dir) / "forge.db"):
            root = Path(temp_dir)
            template_dir = root / "templates"
            template_dir.mkdir()
            filename = BUILTIN_TEMPLATES[0]["filename"]
            existing = template_dir / filename
            existing.write_text("custom content", encoding="utf-8")

            state = list_instruction_templates({
                "templateDir": str(template_dir),
                "configPath": str(root / "config.toml"),
            })

            self.assertEqual("custom content", existing.read_text(encoding="utf-8"))
            self.assertEqual(2, len(state["templates"]))


if __name__ == "__main__":
    unittest.main()
