import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from bridge.commands import _sync_active_auth_to_profile, set_launch_mode
from core.app_server_service import read_account_and_rate_limits
from core.auth_service import is_newer_auth, is_same_auth_account, parse_last_refresh
from core.profile_service import (
    apply_profile, prepare_profile_codex_home, profile_auth_lock,
    sync_codex_home_to_profile, write_profile_auth_json,
)
from core.usage_service import _build_profile_usage, _merge_usage_results


def make_auth(issued=100, user="user-a", workspace="team-a", refresh=None):
    claims = {
        "sub": user, "email": f"{user}@example.com", "iat": issued, "exp": issued + 86400,
        "https://api.openai.com/auth": {
            "chatgpt_user_id": user, "chatgpt_account_id": workspace, "chatgpt_plan_type": "team",
        },
    }
    payload = base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
    token = f"test.{payload}.signature"
    return {
        "auth_mode": "chatgpt", "OPENAI_API_KEY": None,
        "tokens": {"id_token": token, "access_token": token, "refresh_token": f"refresh-{issued}", "account_id": workspace},
        "last_refresh": refresh if refresh is not None else issued,
    }


class AuthSyncTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "profile"
        self.main = self.profile / "auth.json"
        self.runtime = self.profile / "CodexHome" / "auth.json"
        self.system = self.root / "system"
        self.system.mkdir()
        self.addCleanup(patch.stopall)
        patch("core.profile_service.get_active_codex_dir", return_value=self.system).start()
        patch("core.profile_service.DEFAULT_CODEX_ENV_PATH", self.root / "missing.env").start()
        write_profile_auth_json(self.main, make_auth(200))
        write_profile_auth_json(self.runtime, make_auth(100))
        (self.runtime.parent / "config.toml").write_text('cli_auth_credentials_store = "file"\n', encoding="utf-8")

    def read(self, path):
        return json.loads(path.read_text(encoding="utf-8"))

    def server(self, result=None, error=None, updated=None):
        client_patch = patch("core.app_server_service.AppServerClient")
        client_class = client_patch.start()
        client = client_class.return_value.__enter__.return_value

        def request(method, *_args):
            if updated is not None:
                write_profile_auth_json(client_class.call_args.args[0] / "auth.json", updated)
            if method == "account/read":
                return {"account": result}
            if error:
                raise RuntimeError(error)
            return {"rateLimits": {"planType": "team"}}

        client.request.side_effect = request
        patch("core.app_server_service.find_codex_cli_path", return_value=Path("unused.exe")).start()
        return client

    def test_old_runtime_with_new_mtime_cannot_overwrite_main_on_start_or_stop(self):
        newer_mtime = self.main.stat().st_mtime_ns + 10_000_000_000
        os.utime(self.runtime, ns=(newer_mtime, newer_mtime))
        self.assertFalse(sync_codex_home_to_profile(self.profile))
        prepare_profile_codex_home(self.profile)
        self.assertEqual(self.read(self.main), make_auth(200))
        self.assertEqual(self.read(self.runtime), make_auth(200))

    def test_newer_tokens_are_saved_even_if_runtime_file_is_older(self):
        write_profile_auth_json(self.runtime, make_auth(300))
        os.utime(self.runtime, ns=(1_000_000_000, 1_000_000_000))
        prepare_profile_codex_home(self.profile)
        self.assertEqual(self.read(self.main), make_auth(300))

    def test_workspace_and_user_must_both_match(self):
        for candidate in (make_auth(300, user="user-b"), make_auth(300, workspace="team-b")):
            with self.subTest(candidate=candidate["tokens"]["account_id"]):
                write_profile_auth_json(self.runtime, candidate)
                self.assertFalse(sync_codex_home_to_profile(self.profile))
                self.assertEqual(self.read(self.main), make_auth(200))

    def test_shared_team_id_alone_does_not_identify_a_user(self):
        auth = make_auth()
        token = "test." + base64.urlsafe_b64encode(json.dumps({
            "https://api.openai.com/auth": {"chatgpt_account_id": "team-a"},
        }).encode()).decode().rstrip("=") + ".signature"
        auth["tokens"]["id_token"] = token
        self.assertFalse(is_same_auth_account(auth, auth))

    def test_last_refresh_cannot_make_old_access_token_newer(self):
        self.assertFalse(is_newer_auth(make_auth(100, refresh=9999), make_auth(200)))

    def test_unchanged_tokens_do_not_renew_mtime(self):
        before = self.main.stat().st_mtime_ns
        write_profile_auth_json(self.main, make_auth(200))
        self.assertEqual(self.main.stat().st_mtime_ns, before)
        candidate = make_auth(200, refresh=9999)
        self.assertFalse(is_newer_auth(candidate, make_auth(200)))

    def test_fractional_refresh_timestamps_are_supported(self):
        self.assertIsNotNone(parse_last_refresh("2026-11-09T03:51:51.406227500Z"))
        current = make_auth(200, refresh="2026-11-09T03:51:51.100000000Z")
        candidate = make_auth(200, refresh="2026-11-09T03:51:51.406227500Z")
        candidate["tokens"]["refresh_token"] = "rotated"
        self.assertTrue(is_newer_auth(candidate, current))

    def test_missing_account_failure_neither_mislabels_api_key_nor_rewrites_auth(self):
        self.server()
        before = self.main.stat().st_mtime_ns
        with self.assertRaisesRegex(ValueError, "未读取到有效登录账号"):
            read_account_and_rate_limits(self.profile, self.main, None)
        self.assertEqual(self.main.stat().st_mtime_ns, before)

    def test_api_key_and_unsupported_modes_are_distinguished(self):
        self.server(result={"type": "apiKey"})
        with self.assertRaisesRegex(ValueError, "API Key 账号"):
            read_account_and_rate_limits(self.profile, self.main, None)
        self.server(result={"type": "amazonBedrock"})
        with self.assertRaisesRegex(ValueError, "当前认证方式不支持"):
            read_account_and_rate_limits(self.profile, self.main, None)

    def test_failed_quota_query_can_preserve_actual_token_refresh(self):
        self.server(result={"type": "chatgpt"}, error="network error", updated=make_auth(300))
        usage = _build_profile_usage(self.profile, use_codex_home_auth=True)
        self.assertIn("network error", usage["error"])
        self.assertEqual(usage["planType"], "team")
        self.assertEqual(self.read(self.main), make_auth(300))
        self.assertEqual(self.read(self.runtime), make_auth(300))

    def test_failed_query_cannot_install_another_users_tokens(self):
        self.server(result=None, updated=make_auth(300, user="user-b"))
        _build_profile_usage(self.profile, use_codex_home_auth=True)
        self.assertEqual(self.read(self.main), make_auth(200))

    def test_multi_query_uses_fresh_main_and_keeps_plan_on_failure(self):
        client = self.server()
        before = self.main.stat().st_mtime_ns
        usage = _build_profile_usage(self.profile, use_codex_home_auth=True)
        self.assertIn("未读取到有效登录账号", usage["error"])
        self.assertEqual(usage["planType"], "team")
        self.assertEqual(self.read(self.main), make_auth(200))
        self.assertEqual(self.main.stat().st_mtime_ns, before)
        client.request.assert_called_once_with("account/read", {"refreshToken": False})
        self.assertEqual(self.read(self.runtime), make_auth(200))

    def test_active_system_auth_cannot_roll_back_the_main_file(self):
        system_auth = self.system / "auth.json"
        write_profile_auth_json(system_auth, make_auth(100))
        with (
            patch("bridge.commands._get_profile_dir", return_value=self.profile),
            patch("bridge.commands.get_active_auth_path", return_value=system_auth),
        ):
            _sync_active_auth_to_profile({"active_profile": "work"}, "work")
            self.assertEqual(self.read(self.main), make_auth(200))
            write_profile_auth_json(system_auth, make_auth(300))
            _sync_active_auth_to_profile({"active_profile": "work"}, "work")
            self.assertEqual(self.read(self.main), make_auth(300))

    def test_repeated_switch_multi_switch_preserves_tokens_and_workspace_data(self):
        workspace = self.runtime.parent / ".codex-global-state.json"
        workspace.write_bytes(b'{"projects":["existing"],"sections":["work"]}')
        before = workspace.read_bytes()
        config = {"active_profile": "work", "launch_mode": "switch", "profiles": ["work"]}
        with (
            patch("bridge.commands.load_config", return_value=config),
            patch("bridge.commands.save_config"),
            patch("bridge.commands._get_profile_dir", return_value=self.profile),
            patch("bridge.commands._running_multi_profile_names", return_value=[]),
        ):
            for _ in range(3):
                apply_profile(self.profile)
                set_launch_mode({"mode": "multi"})
                prepare_profile_codex_home(self.profile)
                write_profile_auth_json(self.runtime, make_auth(100))
                sync_codex_home_to_profile(self.profile)
                set_launch_mode({"mode": "switch"})
                self.assertEqual(self.read(self.main), make_auth(200))
        self.assertEqual(workspace.read_bytes(), before)

    def test_query_and_launch_share_lock_and_preserve_the_latest_refresh(self):
        entered = threading.Event()
        release = threading.Event()
        launch_started = threading.Event()
        client = self.server(result={"type": "chatgpt"}, updated=make_auth(300))
        original = client.request.side_effect

        def request(method, *args):
            if method == "account/read":
                entered.set()
                if not release.wait(3):
                    raise TimeoutError("test release not received")
            return original(method, *args)

        client.request.side_effect = request

        def prepare():
            launch_started.set()
            prepare_profile_codex_home(self.profile)

        with ThreadPoolExecutor(max_workers=2) as pool:
            query = pool.submit(_build_profile_usage, self.profile, use_codex_home_auth=True)
            self.assertTrue(entered.wait(3))
            launch = pool.submit(prepare)
            self.assertTrue(launch_started.wait(3))
            try:
                self.assertFalse(launch.done())
            finally:
                release.set()
            self.assertIsNone(query.result(timeout=5)["error"])
            launch.result(timeout=5)
        self.assertEqual(self.read(self.main), make_auth(300))
        self.assertEqual(self.read(self.runtime), make_auth(300))

    def test_profile_lock_is_shared_across_processes(self):
        script = (
            "from pathlib import Path; from core.file_lock import _exclusive_file_lock; "
            "import sys; "
            "\ntry:\n with _exclusive_file_lock(Path(sys.argv[1]), timeout_seconds=0): pass"
            "\nexcept TimeoutError: sys.exit(7)"
        )
        with profile_auth_lock(self.profile):
            result = subprocess.run(
                [sys.executable, "-c", script, str(self.profile / ".auth.json.app-server.lock")],
                cwd=Path(__file__).resolve().parents[1], capture_output=True, timeout=5,
            )
        self.assertEqual(result.returncode, 7, result.stderr.decode())

    def test_auth_failure_keeps_known_plan_and_never_claims_quota_success(self):
        current = {"planType": "team", "fetchedAt": 100, "error": None}
        failed = {"planType": None, "fetchedAt": 200, "error": "未读取到有效登录账号", "oneWeek": None}
        with (
            patch("core.usage_service.load_usage_cache", return_value={"work": current}),
            patch("core.usage_service.save_usage_cache"),
            patch("core.usage_service._file_lock"),
        ):
            result = _merge_usage_results({"work": failed}, 150)["work"]
        self.assertEqual(result["planType"], "team")
        self.assertTrue(result["error"])
        self.assertIsNone(result["oneWeek"])


if __name__ == "__main__":
    unittest.main()
