import tempfile
import tomllib
import unittest
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from bridge.commands import (
    _get_legacy_system_running_profile,
    _is_profile_running,
    _is_same_auth_account,
    _resolve_configured_codex_app_path,
    _running_multi_profile_names,
    _stop_client_processes,
    export_profile_backup,
)
from core.codex_source import (
    _get_appx_package_version,
    _is_client_main_process,
    _find_appx_client_path,
    find_windowsapps_codex_path_by_package,
    portable_app_needs_update,
    prepare_portable_codex_path,
    read_running_codex_processes,
    read_source_signature,
    write_source_signature,
)
from core.auth_service import auth_kind
from core.profile_service import (
    get_auth_credentials_store,
    require_file_auth_store,
    sanitize_profile_config_text,
)
from core.usage_service import _map_app_server_usage


class ChatGptCompatibilityTest(unittest.TestCase):
    def test_new_client_entry_processes_and_portable_copy(self):
        self.assertTrue(_is_client_main_process({
            "name": "ChatGPT.exe",
            "command_line": '"C:\\Apps\\ChatGPT.exe"',
            "executable_path": "C:\\Apps\\ChatGPT.exe",
        }))
        self.assertFalse(_is_client_main_process({
            "name": "ChatGPT.exe",
            "command_line": '"C:\\Apps\\ChatGPT.exe" --type=renderer',
            "executable_path": "C:\\Apps\\ChatGPT.exe",
        }))
        self.assertFalse(_is_client_main_process({
            "name": "Codex.exe",
            "command_line": '"C:\\Apps\\resources\\codex.exe" app-server',
            "executable_path": "C:\\Apps\\resources\\codex.exe",
        }))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package_app = root / "OpenAI.Codex_1.0_x64" / "app"
            resources = package_app / "resources"
            resources.mkdir(parents=True)
            (package_app / "ChatGPT.exe").write_bytes(b"chatgpt")
            (package_app / "Codex.exe").write_bytes(b"legacy")
            (resources / "codex.exe").write_bytes(b"app-server")

            with (
                patch("core.codex_source._find_appx_client_path", return_value=""),
                patch("core.codex_source.get_windowsapps_dir", return_value=root),
            ):
                self.assertEqual(find_windowsapps_codex_path_by_package(), str(package_app / "ChatGPT.exe"))

            self.assertEqual(
                _resolve_configured_codex_app_path(resources / "codex.exe"),
                package_app / "ChatGPT.exe",
            )

            profile_dir = root / "profile"
            old_copy = profile_dir / "CodexPortableApp"
            old_copy.mkdir(parents=True)
            (old_copy / "Codex.exe").write_bytes(b"old")
            portable_path = Path(prepare_portable_codex_path(package_app / "ChatGPT.exe", profile_dir))
            self.assertEqual(portable_path, old_copy / "ChatGPT.exe")
            self.assertTrue(portable_path.exists())
            self.assertGreater(read_source_signature(old_copy)["directory_size"], 0)
            self.assertEqual(_get_appx_package_version(package_app / "ChatGPT.exe"), "1.0")
            legacy_signature = read_source_signature(old_copy)
            legacy_signature.pop("package_version")
            write_source_signature(old_copy, legacy_signature)
            self.assertFalse(portable_app_needs_update(package_app / "ChatGPT.exe", old_copy))
            self.assertEqual(read_source_signature(old_copy)["package_version"], "1.0")

    def test_cim_process_and_appx_manifest_payloads_are_parsed(self):
        process_payload = json.dumps([
            {
                "Name": "ChatGPT.exe",
                "ProcessId": 123,
                "ExecutablePath": "C:\\Apps\\ChatGPT.exe",
                "CommandLine": '"C:\\Apps\\ChatGPT.exe"',
            },
            {
                "Name": "ChatGPT.exe",
                "ProcessId": 124,
                "ExecutablePath": "C:\\Apps\\ChatGPT.exe",
                "CommandLine": '"C:\\Apps\\ChatGPT.exe" --type=renderer',
            },
        ])
        appx_payload = json.dumps([
            {"Path": "C:\\Apps\\ChatGPT.exe", "Version": "26.707.1.0"},
        ])
        with patch("core.codex_source.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = process_payload
            self.assertEqual(read_running_codex_processes()[0]["pid"], 123)
            run.return_value.stdout = appx_payload
            with patch("core.codex_source.Path.is_file", return_value=True):
                self.assertEqual(_find_appx_client_path(), "C:\\Apps\\ChatGPT.exe")

    def test_auth_modes_and_credential_store_are_explicit(self):
        self.assertEqual(auth_kind({"OPENAI_API_KEY": "sk-test"}), "api")
        self.assertEqual(auth_kind({"tokens": {"access_token": "token"}}), "chatgpt")

        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.toml"
            self.assertEqual(get_auth_credentials_store(config_path), "file")
            config_path.write_text('cli_auth_credentials_store = "keyring"\n', encoding="utf-8")
            self.assertEqual(get_auth_credentials_store(config_path), "keyring")
            with self.assertRaisesRegex(RuntimeError, "keyring"):
                require_file_auth_store(config_path)

    def test_new_usage_fields_are_mapped(self):
        usage = _map_app_server_usage(
            {"type": "chatgpt", "planType": "team"},
            {
                "rateLimits": {
                    "primary": {"windowDurationMins": 300, "usedPercent": 25},
                    "secondary": {"windowDurationMins": 10080, "usedPercent": 8},
                    "credits": {"hasCredits": True, "unlimited": False},
                    "rateLimitReachedType": "primary",
                },
                "rateLimitResetCredits": {"availableCount": 3},
            },
        )
        self.assertEqual(usage["resetCredits"], 3)
        self.assertTrue(usage["hasCredits"])
        self.assertFalse(usage["creditsUnlimited"])
        self.assertTrue(usage["spendControlReached"])
        self.assertEqual(usage["planType"], "team")
        self.assertEqual(usage["fiveHour"]["remainingPercent"], 75)
        self.assertEqual(usage["oneWeek"]["remainingPercent"], 92)

    def test_profile_config_removes_chatgpt_runtime_state(self):
        source = """model = "gpt-test"
notify = ["C:\\Users\\me\\AppData\\Local\\OpenAI\\Codex\\runtimes\\notify.exe"]
cli_auth_credentials_store = "auto"

[mcp_servers.node_repl]
command = "runtime.exe"

[mcp_servers.node_repl.env]
CODEX_HOME = "C:\\Users\\me\\.codex"

[marketplaces.openai-bundled]
source = "C:\\Users\\me\\.codex\\.tmp"

[mcp_servers.user_service]
command = "user-service.exe"

[hooks.state]
trusted_hash = "dynamic"
"""
        sanitized = sanitize_profile_config_text(source)
        tomllib.loads(sanitized)
        self.assertIn('cli_auth_credentials_store = "file"', sanitized)
        self.assertIn('model = "gpt-test"', sanitized)
        self.assertIn("[mcp_servers.user_service]", sanitized)
        self.assertNotIn("node_repl", sanitized)
        self.assertNotIn("openai-bundled", sanitized)
        self.assertNotIn("trusted_hash", sanitized)
        self.assertNotIn("notify =", sanitized)

    def test_portable_copy_reports_progress_and_keeps_old_copy_on_failure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            (source / "ChatGPT.exe").write_bytes(b"new-client")
            profile = root / "profile"
            old_copy = profile / "CodexPortableApp"
            old_copy.mkdir(parents=True)
            (old_copy / "ChatGPT.exe").write_bytes(b"old-client")
            progress = []

            result = prepare_portable_codex_path(
                source / "ChatGPT.exe",
                profile,
                progress_callback=lambda percent, _copied, _total: progress.append(percent),
            )
            self.assertEqual(Path(result).read_bytes(), b"new-client")
            self.assertEqual(progress[0], 0)
            self.assertEqual(progress[-1], 100)

            (source / "ChatGPT.exe").write_bytes(b"newer-client")
            with patch("core.codex_source._copy_app_directory", side_effect=OSError("copy failed")):
                with self.assertRaisesRegex(OSError, "copy failed"):
                    prepare_portable_codex_path(source / "ChatGPT.exe", profile)
            self.assertEqual((old_copy / "ChatGPT.exe").read_bytes(), b"new-client")

    def test_portable_copy_checks_free_disk_space_before_copying(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source"
            source.mkdir()
            (source / "ChatGPT.exe").write_bytes(b"client")
            with (
                patch("core.codex_source.get_directory_size", return_value=1024),
                patch("core.codex_source.shutil.disk_usage", return_value=SimpleNamespace(free=0)),
            ):
                with self.assertRaisesRegex(OSError, "磁盘空间不足"):
                    prepare_portable_codex_path(source / "ChatGPT.exe", root / "profile")

    def test_profile_backup_excludes_portable_client_copy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            profile_dir = root / "profiles" / "work"
            portable_dir = profile_dir / "CodexPortableApp"
            portable_dir.mkdir(parents=True)
            (profile_dir / "auth.json").write_text("{}", encoding="utf-8")
            (portable_dir / "ChatGPT.exe").write_bytes(b"client")
            codex_home = profile_dir / "CodexHome"
            codex_home.mkdir()
            (codex_home / "config.toml").write_text("model = 'test'", encoding="utf-8")
            (codex_home / "logs_2.sqlite").write_bytes(b"runtime-state")
            plugin_dir = codex_home / "plugins" / "cached-plugin"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "SKILL.md").write_text("runtime plugin", encoding="utf-8")
            app_data = profile_dir / "AppData" / "Roaming"
            app_data.mkdir(parents=True)
            (app_data / "Cookies").write_bytes(b"browser-state")
            config = {"profile_root": str(root / "profiles"), "profiles": ["work"]}

            with patch("bridge.commands.load_config", return_value=config):
                result = export_profile_backup({"name": "work", "targetDir": str(root)})

            with zipfile.ZipFile(result["backupPath"]) as archive:
                self.assertIn("auth.json", archive.namelist())
                self.assertIn("CodexHome/config.toml", archive.namelist())
                self.assertFalse(any(name.startswith("CodexPortableApp/") for name in archive.namelist()))
                self.assertFalse(any(name.startswith("AppData/") for name in archive.namelist()))
                self.assertNotIn("CodexHome/logs_2.sqlite", archive.namelist())
                self.assertNotIn("CodexHome/plugins/cached-plugin/SKILL.md", archive.namelist())

    def test_stop_requests_graceful_exit_before_force(self):
        with (
            patch("bridge.commands.subprocess.run") as run,
            patch("bridge.commands.request_process_close") as request_close,
            patch("bridge.commands.time.monotonic", side_effect=(0, 6)),
        ):
            self.assertEqual(_stop_client_processes([{"pid": 123}]), 1)

        request_close.assert_called_once_with(123)
        self.assertEqual(len(run.call_args_list), 1)
        self.assertIn("/F", run.call_args_list[0].args[0])

    def test_api_key_accounts_use_non_reversible_identity_comparison(self):
        first = {"OPENAI_API_KEY": "sk-first"}
        self.assertTrue(_is_same_auth_account(first, {"OPENAI_API_KEY": "sk-first"}))
        self.assertFalse(_is_same_auth_account(first, {"OPENAI_API_KEY": "sk-second"}))
        self.assertFalse(_is_same_auth_account(first, {"tokens": {"access_token": "token"}}))

    def test_switch_mode_client_remains_associated_after_entering_multi_mode(self):
        config = {"launch_mode": "multi", "profiles": ["first", "second"]}
        with (
            patch("bridge.commands.read_running_codex_commands", return_value=""),
            patch("bridge.commands._get_legacy_system_running_profile", return_value="first"),
        ):
            self.assertTrue(_is_profile_running(config, "first"))
            self.assertFalse(_is_profile_running(config, "second"))
            self.assertEqual(_running_multi_profile_names(config), ["first"])

    def test_legacy_system_client_is_matched_by_its_authenticated_account(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            system_auth_path = root / "system-auth.json"
            (root / "first").mkdir()
            (root / "second").mkdir()
            system_auth_path.write_text(json.dumps({"account": "first"}), encoding="utf-8")
            (root / "first" / "auth.json").write_text(json.dumps({"account": "first"}), encoding="utf-8")
            (root / "second" / "auth.json").write_text(json.dumps({"account": "second"}), encoding="utf-8")
            config = {"launch_mode": "multi", "profile_root": str(root), "profiles": ["first", "second"]}
            with (
                patch("bridge.commands.get_active_auth_path", return_value=system_auth_path),
                patch("bridge.commands.read_running_codex_processes", return_value=[{"command_line": '"C:\\Apps\\ChatGPT.exe"'}]),
                patch("bridge.commands._is_same_auth_account", side_effect=lambda left, right: left == right),
            ):
                self.assertEqual(_get_legacy_system_running_profile(config), "first")


if __name__ == "__main__":
    unittest.main()
