import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge import commands
from core import gateway_client_config as client


class GatewayClientConfigTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.home = Path(temp.name).resolve()
        self.certificate = self.home / client.LAN_CERTIFICATE
        self.certificate.parent.mkdir()
        self.state = self.certificate.with_name("settings.json")
        home = patch.object(client, "_lan_home", return_value=self.home)
        home.start()
        self.addCleanup(home.stop)

    def test_dropped_certificate_is_removed_from_child_environment(self):
        env = {client.CA_VARIABLE: str(self.certificate), "KEEP": "yes"}
        with patch.object(client, "_windows_env", return_value=None):
            self.assertEqual(client.account_client_env(env), {"KEEP": "yes"})
        self.assertIn(client.CA_VARIABLE, env)

    def test_restored_certificate_replaces_the_stale_value(self):
        original = self.home / "original-ca.pem"
        original.touch()
        with patch.object(client, "_windows_env", return_value=str(original)):
            env = client.account_client_env({client.CA_VARIABLE: str(self.certificate)})
        self.assertEqual(env[client.CA_VARIABLE], str(original))

    def test_active_lan_configuration_and_unrelated_certificates_are_kept(self):
        self.certificate.touch()
        self.state.touch()
        with patch.object(client, "_windows_env", return_value=None):
            for cert in (self.certificate, self.home / "custom.pem"):
                env = {client.CA_VARIABLE: str(cert)}
                self.assertEqual(client.account_client_env(env), env)

    def test_switch_back_runs_restore_once_and_settles_without_a_record(self):
        self.state.touch()

        def restore(*args, **kwargs):
            self.state.unlink()
            return subprocess.CompletedProcess(args, 0)

        with (
            patch.dict(os.environ, {"SystemRoot": str(self.home)}),
            patch.object(commands, "_running_codex_count", return_value=0),
            patch.object(client.subprocess, "run", side_effect=restore) as execute,
        ):
            commands.prepare_account_mode()
            commands.prepare_account_mode()
        execute.assert_called_once()
        self.assertEqual(execute.call_args.args[0][-1], "-Restore")
        self.assertEqual(Path(execute.call_args.args[0][-2]).name, "forge-lan-config.ps1")

    def test_switch_back_reports_script_failure_and_retains_restore_record(self):
        self.state.touch()
        failure = subprocess.CompletedProcess([], 1, stdout="配置冲突")
        with (
            patch.dict(os.environ, {"SystemRoot": str(self.home)}),
            patch.object(commands, "_running_codex_count", return_value=0),
            patch.object(client.subprocess, "run", return_value=failure),
            self.assertRaisesRegex(RuntimeError, "配置冲突"),
        ):
            commands.prepare_account_mode()
        self.assertTrue(self.state.is_file())
