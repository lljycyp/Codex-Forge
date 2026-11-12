import base64
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bridge import commands
from core.shared_workspace_service import sync_shared_workspace
from core import shared_workspace_service


ACCOUNT_STATE = "electron-account-renderer-state-v1"
ATOMS = "electron-persisted-atom-state"
SECTIONS = "sidebar-custom-sections-v3"


def owner(user, account="team"):
    return hashlib.sha256(json.dumps([user, account], separators=(",", ":")).encode()).hexdigest()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def project(project_id, path, name="Project"):
    return {"id": project_id, "name": name, "rootPaths": [path], "createdAt": 1, "updatedAt": 1}


def snapshot(projects, section_id="section", account="team"):
    return {
        "globals": {
            "local-projects": projects,
            "project-order": list(projects),
            "thread-project-assignments": {},
        },
        "atoms": {
            SECTIONS: {account: {
                "sections": [{"id": section_id, "name": "后端服务", "itemKeys": [
                    "codex:project:" + p for p in projects
                ], "appearance": None}],
                "sectionOrder": ["custom:" + section_id], "collapsedSectionIds": [],
            }},
        },
    }


class SharedWorkspaceTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.shared = self.root / "forge" / "shared-workspace.json"
        self.home = self.root / "home"
        self.state_path = self.home / ".codex-global-state.json"

    def auth(self, user, account="team"):
        claims = {"https://api.openai.com/auth": {"chatgpt_user_id": user, "chatgpt_account_id": account}}
        token = "header." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".signature"
        path = self.root / (user + ".json")
        write_json(path, {"tokens": {"id_token": token, "account_id": account}})
        return path

    def install_state(self, active, user="a", inactive=None):
        state = {**active["globals"], ATOMS: active["atoms"], ACCOUNT_STATE: {
            "owner": owner(user), "inactive": inactive or {},
        }, "electron-main-window-bounds": {"width": 900}}
        write_json(self.state_path, state)

    def sync(self, user="b", account="team", target=None, homes=None):
        return sync_shared_workspace(
            self.shared, homes or [self.home],
            target_home=target or self.home, auth_path=self.auth(user, account),
        )

    def activate(self, user, account="team", home=None):
        path = (home or self.home) / ".codex-global-state.json"
        state = json.loads(path.read_text("utf-8"))
        bank = state[ACCOUNT_STATE]
        next_owner = owner(user, account)
        if bank["owner"] != next_owner:
            # Model Codex's archive/restore behavior, including an empty target account.
            if bank["owner"] is not None:
                bank["inactive"][bank["owner"]] = {"atoms": state.get(ATOMS, {}), "globals": {
                    k: v for k, v in state.items() if k not in (ACCOUNT_STATE, ATOMS, "electron-main-window-bounds")
                }}
            target = bank["inactive"].pop(next_owner, {"atoms": {}, "globals": {}})
            state = {ACCOUNT_STATE: bank, ATOMS: target["atoms"], **target["globals"]}
            bank["owner"] = next_owner
        write_json(path, state)
        return state

    def test_first_merge_recovers_inactive_projects_deduplicates_paths_and_remaps_membership(self):
        old = snapshot({"old": project("old", "D:\\Work\\Server"), "other": project("other", "D:\\Other")})
        old["globals"]["thread-project-assignments"] = {"t1": {"projectKind": "local", "projectId": "old"}}
        current = snapshot({"new": project("new", "d:/work/server/")}, "new-section")
        current["globals"]["thread-project-assignments"] = {"t2": {"projectKind": "local", "projectId": "new"}}
        self.install_state(current, inactive={owner("old"): old})
        original = self.state_path.read_bytes()

        result = self.sync()
        state = self.activate("b")

        self.assertEqual(result["projectCount"], 2)
        self.assertEqual(len(state["local-projects"]), 2)
        self.assertEqual(state["thread-project-assignments"]["t2"]["projectId"], "old")
        self.assertEqual(len(state[ATOMS][SECTIONS]["team"]["sections"]), 1)
        self.assertTrue(any(p.read_bytes() == original for p in self.shared.parent.rglob("*.bak")))

    def test_account_settings_cloud_items_and_auth_are_preserved(self):
        current = snapshot({"p": project("p", "D:\\Code")})
        target = snapshot({}, "personal", "another-team")
        target["atoms"]["agent-mode-by-host-id"] = {"local": "read-only"}
        target["atoms"]["chatgpt-sidebar-state-v2"] = {"secret": "account-only"}
        target["atoms"][SECTIONS]["another-team"]["sections"][0]["itemKeys"] = ["chatgpt:project:cloud"]
        self.install_state(current, inactive={owner("b", "another-team"): target})
        auth_path = self.auth("b", "another-team")
        original_auth = auth_path.read_bytes()

        self.sync(account="another-team")
        state = self.activate("b", "another-team")

        self.assertEqual(state[ATOMS]["agent-mode-by-host-id"], {"local": "read-only"})
        self.assertEqual(state[ATOMS]["chatgpt-sidebar-state-v2"], {"secret": "account-only"})
        self.assertIn("chatgpt:project:cloud", state[ATOMS][SECTIONS]["another-team"]["sections"][0]["itemKeys"])
        self.assertEqual(auth_path.read_bytes(), original_auth)

    def test_edits_and_deletions_survive_a_b_a_without_reviving_inactive_snapshots(self):
        self.install_state(snapshot({"p": project("p", "D:\\Code"), "q": project("q", "D:\\Other")}))
        self.sync()
        state = self.activate("b")
        state["local-projects"]["p"]["name"] = "Renamed"
        del state["local-projects"]["q"]
        state["project-order"] = ["p"]
        section = state[ATOMS][SECTIONS]["team"]["sections"][0]
        section["name"] = "服务端"
        section["itemKeys"] = ["codex:project:p"]
        write_json(self.state_path, state)

        self.sync("a")
        state = self.activate("a")
        self.assertEqual(list(state["local-projects"]), ["p"])
        self.assertEqual(state["local-projects"]["p"]["name"], "Renamed")
        self.assertEqual(state[ATOMS][SECTIONS]["team"]["sections"][0]["name"], "服务端")
        self.sync("b")
        self.assertEqual(list(self.activate("b")["local-projects"]), ["p"])

    def test_concurrent_instance_changes_merge_without_stale_instance_overwrite(self):
        self.install_state(snapshot({"p": project("p", "D:\\Code")}))
        second_home = self.root / "second"
        self.sync("a")
        self.activate("a")
        self.sync("b", target=second_home)
        second = self.activate("b", home=second_home)
        first = json.loads(self.state_path.read_text("utf-8"))
        first["local-projects"]["p"]["name"] = "Changed by A"
        write_json(self.state_path, first)
        sync_shared_workspace(self.shared, [self.home])
        second["local-projects"]["q"] = project("q", "D:\\New")
        second["project-order"].append("q")
        write_json(second_home / ".codex-global-state.json", second)

        self.sync("a", homes=[self.home, second_home])
        state = self.activate("a")
        self.assertEqual(state["local-projects"]["p"]["name"], "Changed by A")
        self.assertIn("q", state["local-projects"])

    def test_same_home_server_mappings_reused_but_not_copied_to_another_home(self):
        old = snapshot({"p": project("p", "D:\\Code")})
        host = "local:" + str(self.home)
        old["globals"]["app-server-project-id-by-legacy-project-id-by-host"] = {host: {"p": "server-id"}}
        self.install_state(snapshot({}), inactive={owner("old"): old})
        self.sync()
        state = self.activate("b")
        self.assertEqual(state["app-server-project-id-by-legacy-project-id-by-host"][host]["p"], "server-id")
        second_home = self.root / "second"
        self.sync("c", target=second_home)
        second = self.activate("c", home=second_home)
        self.assertNotIn(host, second.get("app-server-project-id-by-legacy-project-id-by-host", {}))

    def test_malformed_state_fails_without_replacing_existing_data(self):
        self.install_state(snapshot({"p": project("p", "D:\\Code")}))
        self.sync()
        shared_before = self.shared.read_bytes()
        self.state_path.write_text('{"broken":', encoding="utf-8")
        with self.assertRaises(ValueError):
            self.sync()
        self.assertEqual(self.shared.read_bytes(), shared_before)
        self.assertEqual(self.state_path.read_text("utf-8"), '{"broken":')

    def test_invalid_identity_does_not_modify_state(self):
        self.install_state(snapshot({"p": project("p", "D:\\Code")}))
        auth = self.root / "invalid-auth.json"
        write_json(auth, {"tokens": {"id_token": "invalid"}})
        before = self.state_path.read_bytes()
        with self.assertRaises(ValueError):
            sync_shared_workspace(self.shared, [self.home], target_home=self.home, auth_path=auth)
        self.assertEqual(before, self.state_path.read_bytes())

    def test_deleted_section_is_not_restored_from_an_unchanged_account(self):
        self.install_state(snapshot({"p": project("p", "D:\\Code")}))
        self.sync()
        state = self.activate("b")
        state[ATOMS][SECTIONS]["team"]["sections"] = []
        state[ATOMS][SECTIONS]["team"]["sectionOrder"] = []
        write_json(self.state_path, state)
        self.sync("a")
        self.assertEqual(self.activate("a")[ATOMS][SECTIONS]["team"]["sections"], [])
        self.sync("b")
        self.assertEqual(self.activate("b")[ATOMS][SECTIONS]["team"]["sections"], [])

    def test_section_server_identity_is_reused_in_the_same_home(self):
        old = snapshot({"p": project("p", "D:\\Code")})
        old["atoms"][SECTIONS]["team"]["sections"][0]["hostSectionIds"] = {"local": "server-section"}
        self.install_state(snapshot({}), inactive={owner("old"): old})
        self.sync()
        section = self.activate("b")[ATOMS][SECTIONS]["team"]["sections"][0]
        self.assertEqual(section["hostSectionIds"], {"local": "server-section"})

    def test_repeated_sync_is_idempotent(self):
        self.install_state(snapshot({"p": project("p", "D:\\Code")}))
        self.sync()
        self.activate("b")
        self.sync()
        first = self.state_path.read_bytes(), self.shared.read_bytes()
        self.sync()
        self.assertEqual(first, (self.state_path.read_bytes(), self.shared.read_bytes()))

    def test_stale_edit_after_concurrent_deletion_preserves_a_complete_project(self):
        self.install_state(snapshot({"p": project("p", "D:\\Code")}))
        other = self.root / "other"
        self.sync("a")
        first = self.activate("a")
        self.sync("b", target=other)
        second = self.activate("b", home=other)
        first["local-projects"] = {}
        write_json(self.state_path, first)
        sync_shared_workspace(self.shared, [self.home])
        second["local-projects"]["p"]["name"] = "Concurrent rename"
        write_json(other / ".codex-global-state.json", second)
        self.sync("a", homes=[self.home, other])
        restored = self.activate("a")["local-projects"]["p"]
        self.assertEqual(restored["rootPaths"], ["D:\\Code"])
        self.assertEqual(restored["name"], "Concurrent rename")

    def test_manual_sidebar_order_and_project_pins_are_shared(self):
        state = snapshot({"p": project("p", "D:\\Code"), "q": project("q", "D:\\Other")})
        state["atoms"]["unified-sidebar-project-order-v1"] = ["codex:project:q", "codex:project:p"]
        state["atoms"]["unified-sidebar-pinned-order-v1"] = ["codex:project:q", "chatgpt:project:private"]
        self.install_state(state)
        self.sync()
        projected = self.activate("b")
        self.assertEqual(projected["project-order"], ["q", "p"])
        self.assertEqual(projected[ATOMS]["unified-sidebar-pinned-order-v1"], ["codex:project:q"])

    def test_switch_prepares_shared_workspace_before_changing_auth(self):
        events = []
        config = {"profiles": ["b"], "launch_mode": "switch"}
        with (
            patch.object(commands, "load_config", return_value=config),
            patch.object(commands, "_running_codex_count", return_value=0),
            patch.object(commands, "_get_profile_dir", return_value=self.root / "b"),
            patch.object(commands, "_sync_shared_workspace", side_effect=lambda *a: events.append("share")),
            patch.object(commands, "apply_profile", side_effect=lambda *a, **k: events.append("auth")),
            patch.object(commands, "save_config"),
            patch.object(commands, "_launch_default_codex", side_effect=lambda *a, **k: events.append("launch") or {}),
        ):
            commands.launch_profile({"name": "b"})
        self.assertEqual(events, ["share", "auth", "launch"])

    def test_failed_share_does_not_switch_auth_or_launch(self):
        with (
            patch.object(commands, "load_config", return_value={"profiles": ["b"]}),
            patch.object(commands, "_running_codex_count", return_value=0),
            patch.object(commands, "_get_profile_dir", return_value=self.root / "b"),
            patch.object(commands, "_sync_shared_workspace", side_effect=ValueError("Invalid state")),
            patch.object(commands, "apply_profile") as apply,
            patch.object(commands, "_launch_default_codex") as launch,
        ):
            with self.assertRaises(ValueError):
                commands.launch_profile({"name": "b"})
        apply.assert_not_called()
        launch.assert_not_called()

    def test_still_running_client_is_not_written(self):
        with (
            patch.object(commands, "load_config", return_value={"profiles": ["b"]}),
            patch.object(commands, "_running_codex_count", return_value=1),
            patch.object(commands, "_stop_running_codex_processes"),
            patch.object(commands, "_sync_shared_workspace") as share,
        ):
            with self.assertRaisesRegex(RuntimeError, "尚未完全退出"):
                commands.launch_profile({"name": "b", "stopRunningFirst": True})
        share.assert_not_called()

    def test_failed_target_write_keeps_original_and_can_be_retried(self):
        self.install_state(snapshot({"p": project("p", "D:\\Code")}))
        original = self.state_path.read_bytes()
        atomic_write = shared_workspace_service._atomic_write

        def fail_target(path, value):
            if path == self.state_path.resolve():
                raise PermissionError("locked")
            atomic_write(path, value)

        with patch.object(shared_workspace_service, "_atomic_write", side_effect=fail_target):
            with self.assertRaises(PermissionError):
                self.sync()
        self.assertEqual(self.state_path.read_bytes(), original)
        self.sync()
        self.assertIn("p", self.activate("b")["local-projects"])

    def test_corrupt_codex_backup_is_preserved_and_replaced_from_valid_state(self):
        self.install_state(snapshot({"p": project("p", "D:\\Code")}))
        backup = self.home / ".codex-global-state.json.bak"
        backup.write_text("incomplete", encoding="utf-8")
        self.sync()
        self.assertEqual(json.loads(backup.read_text("utf-8")), json.loads(self.state_path.read_text("utf-8")))
        self.assertTrue(any(p.read_bytes() == b"incomplete" for p in self.shared.parent.rglob("*.bak")))

    def test_unknown_account_state_version_is_rejected_without_writes(self):
        self.install_state(snapshot({"p": project("p", "D:\\Code")}))
        state = json.loads(self.state_path.read_text("utf-8"))
        state["electron-account-renderer-state-v2"] = state.pop(ACCOUNT_STATE)
        write_json(self.state_path, state)
        with self.assertRaisesRegex(ValueError, "格式已更新"):
            self.sync()
        self.assertFalse(self.shared.exists())

    def test_api_key_profile_does_not_lose_its_existing_launch_behavior(self):
        self.install_state(snapshot({"p": project("p", "D:\\Code")}))
        api_auth = self.root / "api.json"
        write_json(api_auth, {"OPENAI_API_KEY": "test-only-key"})
        original = self.state_path.read_bytes()
        sync_shared_workspace(self.shared, [self.home], target_home=self.home, auth_path=api_auth)
        self.assertEqual(self.state_path.read_bytes(), original)

    def test_invalid_account_owner_does_not_create_shared_data(self):
        self.install_state(snapshot({"p": project("p", "D:\\Code")}))
        state = json.loads(self.state_path.read_text("utf-8"))
        state[ACCOUNT_STATE]["owner"] = {"unknown": "identity"}
        write_json(self.state_path, state)
        with self.assertRaisesRegex(ValueError, "账号状态结构"):
            self.sync()
        self.assertFalse(self.shared.exists())


if __name__ == "__main__":
    unittest.main()
