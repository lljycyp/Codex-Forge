import tempfile
import unittest
from pathlib import Path

from core.usage_service import _resolve_usage_urls


class UsageUrlTest(unittest.TestCase):
    def test_default_usage_url_only_uses_backend_api(self):
        self.assertEqual(
            _resolve_usage_urls(),
            ["https://chatgpt.com/backend-api/wham/usage"],
        )

    def test_custom_backend_base_url_keeps_default_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            config_path.write_text(
                'chatgpt_base_url = "https://example.test/backend-api"\n',
                encoding="utf-8",
            )

            self.assertEqual(
                _resolve_usage_urls(config_path),
                [
                    "https://example.test/backend-api/wham/usage",
                    "https://chatgpt.com/backend-api/wham/usage",
                ],
            )


if __name__ == "__main__":
    unittest.main()
