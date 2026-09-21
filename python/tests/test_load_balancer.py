import io
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch

from core import db
from core.config_store import default_config, load_config, save_config
from core.load_balancer import Gateway, load_key, portable_request, read_accounts, save_enabled


def account(index):
    return {"id": str(index), "name": f"Account {index}", "identity": str(index),
            "reason": "", "token": f"access-{index}", "account_id": f"upstream-{index}"}


class Stream(io.BytesIO):
    status = 200


class GatewayTest(unittest.TestCase):
    def setUp(self):
        self.accounts = [account(1), account(2), account(3)]
        self.opener = Mock()
        self.opener.open.side_effect = lambda *a, **kw: Stream(b'data: {"type":"response.completed"}\n\n')
        self.gateway = Gateway(lambda: self.accounts, self.opener)
        self.gateway.start(0, "test-key")
        self.client = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def tearDown(self):
        self.gateway.stop()

    def wait_idle(self):
        deadline = time.monotonic() + 2
        while self.gateway.status()["activeRequests"] and time.monotonic() < deadline:
            time.sleep(0.005)
        self.assertEqual(self.gateway.status()["activeRequests"], 0)

    def post(self, key="test-key", body=None, headers=None, path="/v1/responses"):
        body = body if body is not None else {"model": "test-model", "stream": True, "store": False, "input": []}
        request = urllib.request.Request(f"http://127.0.0.1:{self.gateway.port}{path}",
                                         data=json.dumps(body).encode(),
                                         headers={"Authorization": "Bearer " + key, **(headers or {})})
        return self.client.open(request, timeout=3)

    def test_key_validation_does_not_contact_upstream(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post(key="wrong")
        self.assertEqual(error.exception.code, 401)
        error.exception.close()
        self.opener.open.assert_not_called()

    def test_same_session_alternates_accounts_and_only_forwards_upstream_credentials(self):
        for _ in range(3):
            with self.post(headers={"session_id": "same-session"}) as response:
                self.assertIn(b"response.completed", response.read())
        sent = [call.args[0] for call in self.opener.open.call_args_list]
        self.assertEqual([r.get_header("Authorization") for r in sent], ["Bearer access-1", "Bearer access-2", "Bearer access-3"])
        self.assertEqual([r.get_header("Chatgpt-account-id") for r in sent], ["upstream-1", "upstream-2", "upstream-3"])
        self.assertTrue(all(r.full_url == "https://chatgpt.com/backend-api/codex/responses" for r in sent))
        status = self.gateway.status()
        self.assertEqual(status["activeRequests"], 0)
        self.assertNotIn("access-", json.dumps(status))
        self.assertNotIn("test-key", json.dumps(status))

    def test_concurrent_acquisition_respects_capacity(self):
        with ThreadPoolExecutor(max_workers=12) as workers:
            results = list(workers.map(lambda _: self.gateway.acquire()[0], range(30)))
        accepted = [a for a in results if a]
        self.assertEqual(len(accepted), 6)
        self.assertEqual(self.gateway.active, {"1": 2, "2": 2, "3": 2})
        for a in accepted:
            self.gateway.release(a, "test", 200, "completed", 0)
        self.assertEqual(self.gateway.status()["activeRequests"], 0)

    def test_stop_blocks_new_requests_but_keeps_existing_lease(self):
        acquired, _ = self.gateway.acquire()
        self.gateway.stop()
        self.assertIsNone(self.gateway.acquire()[0])
        self.assertEqual(self.gateway.status()["activeRequests"], 1)
        self.gateway.release(acquired, "test", 200, "completed", 0)
        self.assertEqual(self.gateway.status()["activeRequests"], 0)

    def test_429_cools_account_without_replaying_and_releases_lease(self):
        self.opener.open.side_effect = urllib.error.HTTPError("upstream", 429, "limited", Message(),
            io.BytesIO(json.dumps({"error": {"resets_at": time.time() + 3600}}).encode()))
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post()
        self.assertEqual(error.exception.code, 429)
        error.exception.close()
        self.assertEqual(self.opener.open.call_count, 1)
        self.wait_idle()
        acquired, _ = self.gateway.acquire()
        assert acquired is not None
        self.assertEqual(acquired["identity"], "2")
        self.gateway.release(acquired, "test", 200, "completed", 0)

    def test_stateful_and_unsupported_requests_are_not_sent_upstream(self):
        for extra in ({"previous_response_id": "response-a"}, {"conversation": "conversation-a"},
                      {"input": [{"type": "input_file", "file_id": "file-a"}]},
                      {"input": [{"type": "compaction", "encrypted_content": "opaque"}]}):
            with self.subTest(extra=extra):
                with self.assertRaises(urllib.error.HTTPError) as error:
                    self.post(body={"model": "test", "stream": True, "store": False, "input": [], **extra})
                self.assertEqual(error.exception.code, 400)
                error.exception.close()
        self.opener.open.assert_not_called()

    def test_network_failure_releases_capacity(self):
        self.opener.open.side_effect = TimeoutError()
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.post()
        self.assertEqual(error.exception.code, 502)
        error.exception.close()
        self.wait_idle()

    def test_incomplete_stream_not_reported_as_success(self):
        self.opener.open.side_effect = lambda *a, **kw: Stream(b'data: {"type":"response.created"}\n\n')
        with self.post() as response:
            response.read()
        self.assertEqual(self.gateway.status()["recentRequests"][0]["outcome"], "incomplete_stream")


class GatewayStorageTest(unittest.TestCase):
    def test_real_service_switch_persistence_and_eof_cleanup_in_isolated_home(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "CodexForge"
            data.mkdir()
            with patch.object(db, "DB_PATH", data / "codex_forge.db"):
                cfg = default_config()
                cfg.update(load_balancer_port=0, profile_root=str(root / "profiles"))
                save_config(cfg)
            env = {**os.environ, "LOCALAPPDATA": str(root), "USERPROFILE": str(root), "HOME": str(root)}
            command = [sys.executable, "-m", "bridge.cli", "run_load_balancer"]
            def run(messages):
                result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env,
                    input="".join(json.dumps(m) + "\n" for m in messages), capture_output=True,
                    text=True, encoding="utf-8", timeout=10, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                self.assertEqual(result.returncode, 0, result.stderr)
                return [json.loads(line) for line in result.stdout.splitlines()]
            first = run([{"id": 1, "command": "set_enabled", "enabled": True}])
            self.assertFalse(first[0]["data"]["enabled"])
            self.assertTrue(first[1]["data"]["running"])
            import socket
            from urllib.parse import urlsplit
            with socket.socket() as client:
                self.assertNotEqual(client.connect_ex(("127.0.0.1", urlsplit(first[1]["data"]["baseUrl"]).port)), 0)
            second = run([{"id": 1, "command": "set_enabled", "enabled": False}])
            self.assertTrue(second[0]["data"]["enabled"])
            self.assertFalse(second[1]["data"]["running"])
            third = run([])
            self.assertFalse(third[0]["data"]["enabled"])

    def test_switch_defaults_off_and_saves_without_rewriting_profiles(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(db, "DB_PATH", Path(directory)/"test.db"):
            self.assertFalse(default_config()["load_balancer_enabled"])
            cfg = default_config()
            cfg["profiles"] = ["one", "two"]
            save_config(cfg)
            before = db.list_profile_records()
            save_enabled(True)
            self.assertTrue(load_config()["load_balancer_enabled"])
            save_enabled(False)
            self.assertFalse(load_config()["load_balancer_enabled"])
            self.assertEqual(before, db.list_profile_records())

    def test_key_is_encrypted_and_reused(self):
        with tempfile.TemporaryDirectory() as directory, patch("core.load_balancer.CONFIG_DIR", Path(directory)), \
             patch("core.load_balancer.protect_bytes", side_effect=lambda b: b[::-1]), \
             patch("core.load_balancer.unprotect_bytes", side_effect=lambda b: b[::-1]):
            first = load_key()
            self.assertEqual(first, load_key())
            self.assertNotIn(first.encode(), (Path(directory)/"load-balancer-key.bin").read_bytes())

    def test_account_reader_deduplicates_identity_and_does_not_write_auth(self):
        import base64
        with tempfile.TemporaryDirectory() as directory, patch.object(db, "DB_PATH", Path(directory)/"test.db"):
            cfg = default_config()
            cfg.update(profiles=["one", "two", "three"], profile_root=directory)
            save_config(cfg)
            records = db.list_profile_records()
            files = {}
            for index, record in enumerate(records):
                claims = {"sub": "user", "exp": time.time() + (3600 if index < 2 else -10)}
                token = "e30." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".signature"
                path = Path(directory)/record["dir_name"]/"auth.json"
                path.parent.mkdir()
                contents = json.dumps({"tokens": {"access_token": token, "account_id": "same" if index < 2 else "other"}})
                path.write_text(contents)
                files[path] = contents
            accounts = read_accounts()
            self.assertEqual(accounts[0]["reason"], "")
            self.assertIn("重复", accounts[1]["reason"])
            self.assertIn("过期", accounts[2]["reason"])
            self.assertTrue(all(path.read_text() == contents for path, contents in files.items()))

    def test_portability_preserves_full_tool_history(self):
        body = {"model": "test", "stream": True, "store": False, "input": [
            {"type": "reasoning", "encrypted_content": "opaque-reasoning", "summary": []},
            {"type": "function_call", "call_id": "call-1", "name": "test", "arguments": "{}"},
            {"type": "function_call_output", "call_id": "call-1", "output": "ok"}]}
        original = json.dumps(body)
        self.assertEqual(portable_request(body), "")
        self.assertEqual(json.dumps(body), original)


if __name__ == "__main__":
    unittest.main()
