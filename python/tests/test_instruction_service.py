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
            self.assertEqual(5, len(second["templates"]))
            self.assertEqual(first, second)
            self.assertFalse(Path(payload["configPath"]).exists())
            for template in BUILTIN_TEMPLATES:
                self.assertTrue((Path(payload["templateDir"]) / template["filename"]).is_file())

    def test_existing_same_name_template_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch("core.db.DB_PATH", Path(temp_dir) / "forge.db"):
            root = Path(temp_dir)
            template_dir = root / "templates"
            template_dir.mkdir()
            filename = "gpt-6.1-sol.md"
            existing = template_dir / filename
            existing.write_text("custom content", encoding="utf-8")

            state = list_instruction_templates({
                "templateDir": str(template_dir),
                "configPath": str(root / "config.toml"),
            })

            self.assertEqual("custom content", existing.read_text(encoding="utf-8"))
            self.assertEqual(5, len(state["templates"]))

    def test_upgrade_preserves_existing_templates_and_enabled_config(self):
        with tempfile.TemporaryDirectory() as temp_dir, patch("core.db.DB_PATH", Path(temp_dir) / "forge.db"):
            root = Path(temp_dir)
            template_dir = root / "templates"
            template_dir.mkdir()
            legacy_templates = [dict(item) for item in BUILTIN_TEMPLATES[:2]]
            legacy_templates[0]["title"] = "My customized template"
            for template in legacy_templates:
                (template_dir / template["filename"]).write_text("custom content", encoding="utf-8")
            db.save_instruction_templates(str(template_dir.resolve()), legacy_templates)
            config_path = root / "config.toml"
            config_content = b'model_instructions_file = "./gpt-5.6-sol-unrestricted.md"\r\nmodel = "fixture"\r\n'
            config_path.write_bytes(config_content)
            payload = {"templateDir": str(template_dir), "configPath": str(config_path)}

            first = list_instruction_templates(payload)
            second = list_instruction_templates(payload)

            self.assertEqual(first, second)
            self.assertEqual(config_content, config_path.read_bytes())
            self.assertEqual(legacy_templates, [
                {key: item[key] for key in ("id", "title", "filename")}
                for item in first["templates"][:2]
            ])
            self.assertEqual({"gpt-5.6-sol.md", "gpt-6-astra.md", "gpt-6.1-sol.md"}, {
                item["filename"] for item in first["templates"][2:]
            })
            self.assertEqual(["gpt-5.6-sol-unrestricted.md"], [
                item["filename"] for item in first["templates"] if item["enabled"]
            ])
            for template in legacy_templates:
                self.assertEqual("custom content", (template_dir / template["filename"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
