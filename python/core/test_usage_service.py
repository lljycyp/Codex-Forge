import time
import tempfile
import unittest
from pathlib import Path

import core.usage_service as usage_service
from core.usage_service import _resolve_usage_urls, _usage_error


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


class UsageCacheTest(unittest.TestCase):
    def test_transient_error_does_not_replace_success_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            original_path = usage_service.USAGE_CACHE_PATH
            usage_service.USAGE_CACHE_PATH = Path(temp_dir) / "usage_cache.json"
            try:
                cached = {
                    "acct": {
                        "fetchedAt": time.time() - 10,
                        "planType": "team",
                        "fiveHour": {"usedPercent": 1},
                        "oneWeek": {"usedPercent": 2},
                        "error": None,
                    }
                }
                usage_service.save_usage_cache(cached)

                result = usage_service._merge_usage_results(
                    {
                        "acct": _usage_error(
                            "额度读取失败：https://chatgpt.com/backend-api/wham/usage -> "
                            "<urlopen error [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred>"
                        )
                    },
                    time.time(),
                )

                self.assertEqual(result["acct"], cached["acct"])
            finally:
                usage_service.USAGE_CACHE_PATH = original_path


if __name__ == "__main__":
    unittest.main()
