import json
import os
import tempfile
import tomllib
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from bridge.commands import (
    _append_codex_skin_args,
    get_codex_skin_sessions,
    _is_same_auth_account,
    _launch_default_codex,
    _resolve_codex_app_source_path,
    _resolve_configured_codex_app_path,
    _stop_client_processes,
    export_profile_backup,
    ensure_codex_skin_sessions,
    invoke,
    refresh_codex_source,
    set_codex_skin_enabled,
)
from core.codex_source import (
    _is_client_main_process,
    _find_appx_client_path,
    find_windowsapps_codex_path_by_package,
    read_running_codex_processes,
)
from core.auth_service import auth_kind
from core.app_server_service import AppServerClient, _exclusive_file_lock, _remove_temporary_directory
from core.profile_service import (
    get_auth_credentials_store,
    require_file_auth_store,
    sanitize_profile_config_text,
)
from core.usage_service import _map_app_server_usage, _merge_usage_results


class ChatGptCompatibilityTest(unittest.TestCase):
    def test_client_lifecycle_command_uses_cross_process_lock(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config = {"profile_root": temp_dir}
            with (
                patch("bridge.commands.load_config", return_value=config),
                patch("bridge.commands.launch_profile", return_value={"name": "work"}),
                patch("bridge.commands._exclusive_file_lock") as operation_lock,
            ):
                result = invoke("launch_profile", {"name": "work"})

            expected_lock_path = Path(temp_dir) / ".shared" / ".codex-client-operation.lock"
            operation_lock.assert_called_once_with(expected_lock_path, timeout_seconds=120)
            self.assertTrue(result["ok"])

    def test_store_source_prefers_latest_installed_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            windows_apps = Path(temp_dir) / "WindowsApps"
            old_path = windows_apps / "OpenAI.Codex_26.810.4967.0_x64__test" / "app" / "ChatGPT.exe"
            latest_path = windows_apps / "OpenAI.Codex_26.820.7780.0_x64__test" / "app" / "ChatGPT.exe"
            old_path.parent.mkdir(parents=True)
            latest_path.parent.mkdir(parents=True)
            old_path.write_bytes(b"old")
            latest_path.write_bytes(b"latest")
            config = {"codex_path": str(old_path)}

            with (
                patch("bridge.commands.find_windowsapps_codex_path_by_package", return_value=str(latest_path)),
                patch("bridge.commands.save_config") as save_config,
            ):
                resolved_path = _resolve_codex_app_source_path(config)

            self.assertEqual(resolved_path, latest_path)
            self.assertEqual(config["codex_path"], str(latest_path))
            save_config.assert_called_once_with(config)

    def test_refresh_codex_source_reidentifies_latest_store_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            windows_apps = Path(temp_dir) / "WindowsApps"
            old_path = windows_apps / "OpenAI.Codex_26.810.4967.0_x64__test" / "app" / "ChatGPT.exe"
            latest_path = windows_apps / "OpenAI.Codex_26.820.7780.0_x64__test" / "app" / "ChatGPT.exe"
            old_path.parent.mkdir(parents=True)
            latest_path.parent.mkdir(parents=True)
            old_path.write_bytes(b"old")
            latest_path.write_bytes(b"latest")
            config = {"codex_path": str(old_path)}

            with (
                patch("bridge.commands.load_config", return_value=config),
                patch("bridge.commands.find_windowsapps_codex_path_by_package", return_value=str(latest_path)),
                patch("bridge.commands._find_windows_store_codex_app_id", return_value=""),
                patch("bridge.commands.save_config") as save_config,
            ):
                result = refresh_codex_source()

            self.assertEqual(result["codexLaunchPath"], str(latest_path))
            self.assertEqual(config["codex_path"], str(latest_path))
            save_config.assert_called_once_with(config)

    def test_store_source_falls_back_when_latest_package_lookup_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            old_path = Path(temp_dir) / "WindowsApps" / "OpenAI.Codex_26.810.4967.0_x64__test" / "app" / "ChatGPT.exe"
            old_path.parent.mkdir(parents=True)
            old_path.write_bytes(b"old")
            config = {"codex_path": str(old_path)}

            with (
                patch("bridge.commands.find_windowsapps_codex_path_by_package", side_effect=OSError("AppX unavailable")),
                patch("bridge.commands.save_config") as save_config,
            ):
                resolved_path = _resolve_codex_app_source_path(config)

            self.assertEqual(resolved_path, old_path)
            self.assertEqual(config["codex_path"], str(old_path))
            save_config.assert_not_called()

    def test_custom_source_is_not_replaced_by_store_package(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_path = Path(temp_dir) / "CustomCodex" / "ChatGPT.exe"
            custom_path.parent.mkdir(parents=True)
            custom_path.write_bytes(b"custom")
            config = {"codex_path": str(custom_path)}

            with (
                patch("bridge.commands.find_windowsapps_codex_path_by_package") as find_package,
                patch("bridge.commands.save_config") as save_config,
            ):
                resolved_path = _resolve_codex_app_source_path(config)

            self.assertEqual(resolved_path, custom_path)
            find_package.assert_not_called()
            save_config.assert_not_called()

    def test_switch_mode_skin_launches_regular_client_directly_with_cdp(self):
        process = SimpleNamespace(pid=88)
        with (
            patch("bridge.commands.load_config", return_value={}),
            patch("bridge.commands._resolve_codex_app_source_path", return_value=Path("C:/Apps/ChatGPT.exe")),
            patch("bridge.commands.db.load_profile_launch_settings", return_value={"args": [], "env": {}}),
            patch("bridge.commands.subprocess.Popen", return_value=process) as popen,
        ):
            result = _launch_default_codex("work", skin_port=19335)

        command = popen.call_args.args[0]
        self.assertEqual(command[0], "C:\\Apps\\ChatGPT.exe")
        self.assertIn("--remote-debugging-address=127.0.0.1", command)
        self.assertIn("--remote-debugging-port=19335", command)
        skin_session = result.get("skinSession")
        self.assertIsInstance(skin_session, dict)
        assert isinstance(skin_session, dict)
        self.assertEqual(skin_session["profileName"], "work")

    def test_switch_mode_skin_launches_store_alias_with_original_cdp_and_environment(self):
        process = SimpleNamespace(pid=89)
        store_path = Path("C:/Program Files/WindowsApps/OpenAI.Codex_1.0_x64/app/ChatGPT.exe")
        alias_path = Path("C:/Local/Microsoft/WindowsApps/OpenAI.Codex_test/chatgpt-desktop.exe")
        config = {"profile_root": "D:/Profiles"}
        with (
            patch("bridge.commands.load_config", return_value=config),
            patch("bridge.commands._resolve_codex_app_source_path", return_value=store_path),
            patch("bridge.commands.resolve_codex_execution_path", return_value=alias_path) as resolve_execution,
            patch("bridge.commands.db.load_profile_launch_settings", return_value={"args": ["--lang=en-US"], "env": {"CUSTOM_ENV": "value"}}),
            patch("bridge.commands.subprocess.Popen", return_value=process) as popen,
        ):
            result = _launch_default_codex("work", skin_port=19335)

        command = popen.call_args.args[0]
        resolve_execution.assert_called_once_with(store_path)
        self.assertEqual(command[0], str(alias_path))
        self.assertIn("--lang=en-US", command)
        self.assertIn("--remote-debugging-address=127.0.0.1", command)
        self.assertIn("--remote-debugging-port=19335", command)
        self.assertEqual(popen.call_args.kwargs["cwd"], str(store_path.parent))
        self.assertEqual(popen.call_args.kwargs["env"]["CUSTOM_ENV"], "value")
        skin_session = result.get("skinSession")
        self.assertIsInstance(skin_session, dict)
        assert isinstance(skin_session, dict)
        self.assertEqual(skin_session["processId"], 89)

    def test_enabling_skin_restarts_running_switch_profile(self):
        config = {"active_profile": "work", "codex_skin_enabled": False}
        with (
            patch("bridge.commands.load_config", return_value=config),
            patch("bridge.commands._running_codex_count", return_value=1),
            patch("bridge.commands.read_running_codex_commands", return_value="ChatGPT.exe"),
            patch("bridge.commands._sync_active_auth_to_profile") as sync_auth,
            patch("bridge.commands._stop_running_codex_processes") as stop_clients,
            patch("bridge.commands.save_config") as save_config,
            patch("bridge.commands._allocate_codex_skin_port", return_value=19335),
            patch(
                "bridge.commands._launch_default_codex",
                return_value={"skinSession": {"profileName": "work", "port": 19335, "processId": 88}},
            ) as launch_client,
        ):
            result = set_codex_skin_enabled({"enabled": True})

        sync_auth.assert_called_once_with(config, "work")
        stop_clients.assert_called_once_with()
        save_config.assert_called_once_with(config)
        launch_client.assert_called_once_with("work", skin_port=19335)
        self.assertEqual(result["skinSessions"][0]["port"], 19335)

    def test_codex_skin_appends_loopback_debugging_arguments(self):
        self.assertEqual(
            _append_codex_skin_args(["--start-minimized"], 19335),
            [
                "--start-minimized",
                "--remote-debugging-address=127.0.0.1",
                "--remote-debugging-port=19335",
            ],
        )

    def test_codex_skin_rejects_conflicting_debugging_arguments(self):
        with self.assertRaisesRegex(ValueError, "remote-debugging"):
            _append_codex_skin_args(["--remote-debugging-port=9222"], 19335)

    def test_recovers_running_switch_skin_session_from_managed_client(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            shared_root = Path(temp_dir) / ".shared"
            executable = shared_root / "CodexPortableApp" / "ChatGPT.exe"
            config = {
                "profile_root": temp_dir,
                "active_profile": "work",
                "codex_skin_enabled": True,
            }
            process = {
                "pid": 88,
                "executable_path": str(executable),
                "command_line": (
                    f'"{executable}" --remote-debugging-address=127.0.0.1 '
                    "--remote-debugging-port=19335"
                ),
            }
            with (
                patch("bridge.commands.load_config", return_value=config),
                patch("bridge.commands.read_running_codex_processes", return_value=[process]),
            ):
                result = get_codex_skin_sessions()

        self.assertEqual(
            result["skinSessions"],
            [{"profileName": "work", "port": 19335, "processId": 88}],
        )

    def test_skin_session_recovery_rejects_unmanaged_client(self):
        config = {
            "profile_root": "D:/Profiles",
            "launch_mode": "switch",
            "active_profile": "work",
            "codex_skin_enabled": True,
        }
        process = {
            "pid": 89,
            "executable_path": "C:/Other/ChatGPT.exe",
            "command_line": (
                '"C:/Other/ChatGPT.exe" --remote-debugging-address=127.0.0.1 '
                "--remote-debugging-port=19335"
            ),
        }
        with (
            patch("bridge.commands.load_config", return_value=config),
            patch("bridge.commands.read_running_codex_processes", return_value=[process]),
        ):
            self.assertEqual(get_codex_skin_sessions(), {"skinSessions": []})

    def test_store_alias_skin_sessions_are_recovered_without_restarting_clients(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "WindowsApps" / "OpenAI.Codex_1.0_x64__test" / "app" / "ChatGPT.exe"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"client")
            config = {"profile_root": str(root), "codex_path": str(source),
                      "active_profile": "work", "profiles": ["work"], "codex_skin_enabled": True}
            process = {"pid": 91, "executable_path": str(source), "command_line": (
                f'"C:/Local/Microsoft/WindowsApps/OpenAI.Codex_test/chatgpt-desktop.exe" '
                '--remote-debugging-address=127.0.0.1 --remote-debugging-port=19335'
            )}
            with (
                patch("bridge.commands.load_config", return_value=config),
                patch("bridge.commands.read_running_codex_processes", return_value=[process]),
                patch("bridge.commands._running_codex_count", return_value=1),
                patch("bridge.commands._sync_active_auth_to_profile"),
                patch("bridge.commands._stop_running_codex_processes") as stop_clients,
                patch("bridge.commands._launch_default_codex") as launch_default,
            ):
                result = ensure_codex_skin_sessions()

            self.assertEqual(result["skinSessions"], [{"profileName": "work", "port": 19335, "processId": 91}])
            stop_clients.assert_not_called()
            launch_default.assert_not_called()

    def test_ensure_skin_session_restarts_running_switch_client_without_cdp(self):
        config = {
            "launch_mode": "switch",
            "active_profile": "work",
            "codex_skin_enabled": True,
        }
        session = {"profileName": "work", "port": 19335, "processId": 90}
        with (
            patch("bridge.commands.get_codex_skin_sessions", return_value={"skinSessions": []}),
            patch("bridge.commands.load_config", return_value=config),
            patch("bridge.commands._running_codex_count", return_value=1),
            patch("bridge.commands.read_running_codex_commands", return_value="ChatGPT.exe"),
            patch("bridge.commands._sync_active_auth_to_profile") as sync_auth,
            patch("bridge.commands._stop_running_codex_processes") as stop_clients,
            patch("bridge.commands._allocate_codex_skin_port", return_value=19335),
            patch("bridge.commands._launch_default_codex", return_value={"skinSession": session}) as launch_client,
        ):
            result = ensure_codex_skin_sessions()

        sync_auth.assert_called_once_with(config, "work")
        stop_clients.assert_called_once_with()
        launch_client.assert_called_once_with("work", skin_port=19335)
        self.assertEqual(result, {"skinSessions": [session]})

    def test_stale_app_server_lock_is_recovered(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "auth.json.app-server.lock"
            lock_path.write_text("12345", encoding="utf-8")
            with patch("core.file_lock._is_process_running", return_value=False):
                with _exclusive_file_lock(lock_path, timeout_seconds=1):
                    self.assertEqual(lock_path.read_text(encoding="utf-8"), str(os.getpid()))
            self.assertFalse(lock_path.exists())

    def test_running_app_server_lock_is_preserved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "auth.json.app-server.lock"
            lock_path.write_text("12345", encoding="utf-8")
            with patch("core.file_lock._is_process_running", return_value=True):
                with self.assertRaises(TimeoutError):
                    with _exclusive_file_lock(lock_path, timeout_seconds=0):
                        pass
            self.assertEqual(lock_path.read_text(encoding="utf-8"), "12345")

    def test_new_client_entry_processes_and_install_source(self):
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
                    "primary": {"windowDurationMins": 300, "usedPercent": 25, "resetsAt": 3000},
                    "secondary": {"windowDurationMins": 10080, "usedPercent": 8},
                    "credits": {"hasCredits": True, "unlimited": False},
                    "rateLimitReachedType": "primary",
                },
                "rateLimitResetCredits": {
                    "availableCount": 3,
                    "credits": [
                        {"status": "available", "expiresAt": 2000},
                        {"status": "used", "expiresAt": 1000},
                        {"status": "available", "expiresAt": 3000},
                    ],
                },
            },
        )
        self.assertEqual(usage["resetCredits"], 3)
        self.assertEqual(usage["resetCreditExpiresAt"], [2000, 3000])
        self.assertTrue(usage["hasCredits"])
        self.assertFalse(usage["creditsUnlimited"])
        self.assertTrue(usage["spendControlReached"])
        self.assertEqual(usage["planType"], "team")
        self.assertEqual(usage["fiveHours"]["remainingPercent"], 75)
        self.assertEqual(usage["fiveHours"]["resetAt"], 3000)
        self.assertEqual(usage["oneWeek"]["remainingPercent"], 92)

    def test_weekly_usage_is_mapped_without_legacy_window(self):
        usage = _map_app_server_usage(
            {"type": "chatgpt", "planType": "team"},
            {
                "rateLimits": {
                    "primary": {"windowDurationMins": 10080, "usedPercent": 2},
                },
            },
        )

        self.assertEqual(usage["oneWeek"]["remainingPercent"], 98)
        self.assertIsNone(usage["fiveHours"])

    def test_app_server_network_error_keeps_plan_but_reports_failure(self):
        current = {
            "fetchedAt": 100,
            "planType": "team",
            "oneWeek": {"remainingPercent": 94},
            "error": None,
        }
        failed = {
            "fetchedAt": 200,
            "oneWeek": None,
            "error": (
                "额度读取失败：failed to fetch codex rate limits: error sending request for url "
                "(https://chatgpt.com/backend-api/wham/usage)"
            ),
        }

        with (
            patch("core.usage_service.load_usage_cache", return_value={"work": current}),
            patch("core.usage_service.save_usage_cache") as save_usage_cache,
            patch("core.usage_service._file_lock"),
        ):
            result = _merge_usage_results({"work": failed}, started_at=150)

        expected = {**failed, "planType": "team"}
        self.assertEqual(result["work"], expected)
        save_usage_cache.assert_called_once_with({"work": expected})

    def test_app_server_network_error_is_kept_without_successful_usage(self):
        failed = {
            "fetchedAt": 200,
            "oneWeek": None,
            "error": "额度读取失败：failed to fetch codex rate limits: error sending request for url",
        }

        with (
            patch("core.usage_service.load_usage_cache", return_value={}),
            patch("core.usage_service.save_usage_cache") as save_usage_cache,
            patch("core.usage_service._file_lock"),
        ):
            result = _merge_usage_results({"work": failed}, started_at=150)

        self.assertEqual(result["work"], failed)
        save_usage_cache.assert_called_once_with({"work": failed})

    def test_app_server_temp_cleanup_retries_marketplace_race(self):
        path = Path(tempfile.gettempdir()) / "codex-forge-account-test"
        directory_not_empty = OSError(145, "目录不是空的", str(path / ".git"))
        with (
            patch("core.app_server_service.shutil.rmtree", side_effect=(directory_not_empty, None)) as rmtree,
            patch("core.app_server_service.time.sleep") as sleep,
        ):
            _remove_temporary_directory(path)

        self.assertEqual(rmtree.call_count, 2)
        sleep.assert_called_once()

    def test_windows_app_server_exit_kills_process_tree_before_closing_stdin(self):
        events = Mock()
        process = Mock(pid=12345)
        process.poll.side_effect = (None, 0)
        process.stdin.close.side_effect = lambda: events.stdin_closed()
        client = AppServerClient("C:\\Temp\\codex-home", "C:\\Temp\\codex.exe")
        client.process = process

        with (
            patch("core.app_server_service.os.name", "nt"),
            patch("core.app_server_service.subprocess.run", side_effect=lambda *args, **kwargs: events.tree_killed()),
        ):
            client.__exit__(None, None, None)

        self.assertEqual(events.mock_calls, [call.tree_killed(), call.stdin_closed()])
        process.wait.assert_called_once_with(timeout=3)

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
            (codex_home / "auth.json").write_text('{"runtime":true}', encoding="utf-8")
            (codex_home / "config.toml").write_text("model = 'test'", encoding="utf-8")
            (codex_home / "logs_2.sqlite").write_bytes(b"runtime-state")
            plugin_dir = codex_home / "plugins" / "cached-plugin"
            plugin_dir.mkdir(parents=True)
            (plugin_dir / "SKILL.md").write_text("runtime plugin", encoding="utf-8")
            app_data = profile_dir / "AppData" / "Roaming"
            app_data.mkdir(parents=True)
            (app_data / "Cookies").write_bytes(b"browser-state")
            config = {"profile_root": str(root / "profiles"), "profiles": ["work"]}

            with (
                patch("bridge.commands.load_config", return_value=config),
                patch("bridge.commands.db.get_profile", return_value={"dir_name": "work"}),
            ):
                result = export_profile_backup({"name": "work", "targetDir": str(root)})

            with zipfile.ZipFile(result["backupPath"]) as archive:
                self.assertNotIn("auth.json", archive.namelist())
                self.assertNotIn("CodexHome/auth.json", archive.namelist())
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
