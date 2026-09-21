import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

from core.load_balancer_client import prepare_client, launch_client


class DedicatedClientTest(unittest.TestCase):
    def test_config_and_environment_are_isolated_and_do_not_copy_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "original.toml"
            text = 'model = "test-model"\n[mcp_servers.private]\ncommand = "secret-command"\n'
            source.write_text(text)
            with patch("core.load_balancer_client.get_active_config_path", return_value=source), patch.dict(os.environ, {
                "OPENAI_API_KEY": "original-key", "CODEX_SQLITE_HOME": "original-state", "FORGE_GATEWAY_KEY": "old-key",
                "CODEX_APP_TOOLS_PIPE_PATH": "parent-pipe", "CODEX_THREAD_ID": "parent-thread",
            }):
                home, user_data, env = prepare_client(root / "client", "http://127.0.0.1:12345/v1", "local-only-key")
                self.assertEqual(os.environ["OPENAI_API_KEY"], "original-key")
            config = tomllib.loads((home / "config.toml").read_text())
            self.assertEqual(config["model"], "test-model")
            self.assertEqual(config["model_provider"], "forge")
            self.assertNotIn("mcp_servers", config)
            self.assertFalse(config["model_providers"]["forge"]["supports_websockets"])
            self.assertEqual(env["FORGE_GATEWAY_KEY"], "local-only-key")
            self.assertNotIn("OPENAI_API_KEY", env)
            self.assertNotIn("CODEX_SQLITE_HOME", env)
            self.assertNotIn("CODEX_APP_TOOLS_PIPE_PATH", env)
            self.assertNotIn("CODEX_THREAD_ID", env)
            self.assertEqual(env["CODEX_ELECTRON_USER_DATA_PATH"], str(user_data))
            self.assertNotIn("local-only-key", (home / "config.toml").read_text())
            self.assertFalse((home / "auth.json").exists())
            self.assertEqual(source.read_text(), text)

    def test_refuses_to_overwrite_a_home_with_real_login(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            home = root / "CodexHome"
            home.mkdir()
            config = home / "config.toml"
            config.write_text('model = "test"\n')
            auth = home / "auth.json"
            content = json.dumps({"tokens": {"access_token": "real-token"}})
            auth.write_text(content)
            with self.assertRaisesRegex(ValueError, "退出登录"):
                prepare_client(root, "http://127.0.0.1:123/v1", "key")
            self.assertEqual(auth.read_text(), content)
            self.assertEqual(config.read_text(), 'model = "test"\n')

    def test_repeated_launch_does_not_modify_running_client(self):
        with tempfile.TemporaryDirectory() as directory, patch("core.load_balancer_client.CONFIG_DIR", Path(directory)), \
             patch("core.load_balancer_client.read_running_codex_processes", return_value=[{
                 "command_line": f'ChatGPT.exe --user-data-dir={directory}\\load-balancer-client\\UserData'
             }]), patch("core.load_balancer_client.prepare_client") as prepare, \
             patch("core.load_balancer_client.subprocess.Popen") as spawn:
            result = launch_client({}, "http://127.0.0.1:123/v1", "key")
            self.assertTrue(result["alreadyRunning"])
            prepare.assert_not_called()
            spawn.assert_not_called()

    def test_restart_preserves_desktop_settings_while_updating_address(self):
        with tempfile.TemporaryDirectory() as directory, patch("core.load_balancer_client.get_active_config_path", return_value=Path(directory)/"absent"):
            home, _, _ = prepare_client(directory, "http://127.0.0.1:123/v1", "key")
            path = home / "config.toml"
            content = path.read_text().replace('model = "gpt-6-astra"', 'model = "chosen-model"')
            path.write_text(content + '\n[windows]\nsandbox = "unelevated"\n')
            prepare_client(directory, "http://127.0.0.1:456/v1", "key")
            config = tomllib.loads(path.read_text())
            self.assertEqual(config["model"], "chosen-model")
            self.assertEqual(config["windows"]["sandbox"], "unelevated")
            self.assertEqual(config["model_providers"]["forge"]["base_url"], "http://127.0.0.1:456/v1")

    def test_launch_uses_dedicated_directories_and_child_only_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            app = root / "app/ChatGPT.exe"
            app.parent.mkdir()
            app.touch()
            (app.parent / "resources").mkdir()
            (app.parent / "resources/app.asar").touch()
            with patch("core.load_balancer_client.CONFIG_DIR", root / "forge"), \
                 patch("core.load_balancer_client.read_running_codex_processes", return_value=[]), \
                 patch("core.load_balancer_client.find_codex_cli_path", return_value=root / "codex.exe"), \
                 patch("core.load_balancer_client.get_active_config_path", return_value=root / "absent"), \
                 patch("core.load_balancer_client.subprocess.Popen") as spawn:
                spawn.return_value.pid = 123
                result = launch_client({"codex_path": str(app)}, "http://127.0.0.1:19380/v1", "child-only-key")
            args, kwargs = spawn.call_args
            self.assertEqual(result["processId"], 123)
            self.assertIn("load-balancer-client", args[0][1])
            self.assertNotIn("child-only-key", str(args))
            self.assertEqual(kwargs["env"]["FORGE_GATEWAY_KEY"], "child-only-key")
            self.assertTrue(Path(kwargs["env"]["CODEX_HOME"]).is_relative_to((root / "forge").resolve()))
