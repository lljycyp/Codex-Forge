"""共享本机项目与分区；只在目标 Codex 退出后写入其账号快照。"""

import hashlib
import json
import ntpath
import os
import time
import uuid
from copy import deepcopy
from pathlib import Path

from core.app_server_service import _exclusive_file_lock
from core.auth_service import auth_kind, auth_tokens, decode_jwt_payload


STATE_FILE = ".codex-global-state.json"
ACCOUNT_STATE = "electron-account-renderer-state-v1"
ATOMS = "electron-persisted-atom-state"
SECTIONS = "sidebar-custom-sections-v3"
PROJECT_PREFIX = "codex:project:"
THREAD_PREFIX = "codex:thread:local:"
SERVER_IDS = "app-server-project-id-by-legacy-project-id-by-host"
MIGRATIONS = "app-server-projects-migration-by-host"
_MISSING = object()


def _read_json(path):
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"共享工作区无法读取 JSON，原文件未覆盖：{path}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"共享工作区状态必须是 JSON 对象：{path}")
    return value


def _identity(auth_path):
    auth = _read_json(Path(auth_path))
    if auth_kind(auth) == "api":
        return None
    tokens = auth_tokens(auth) or {}
    for key in ("id_token", "access_token"):
        claims = decode_jwt_payload(tokens.get(key))
        claim = claims.get("https://api.openai.com/auth") or {}
        user = claim.get("chatgpt_user_id") or claim.get("user_id")
        account = tokens.get("account_id") or tokens.get("chatgpt_account_id") or claim.get("chatgpt_account_id")
        if isinstance(user, str) and user and isinstance(account, str) and account:
            value = json.dumps([user, account], ensure_ascii=False, separators=(",", ":"))
            return hashlib.sha256(value.encode("utf-8")).hexdigest(), account
    raise ValueError("无法识别共享工作区的目标账号，请检查账号登录信息")


def _records(home, state):
    bank = state.get(ACCOUNT_STATE, {})
    if (not isinstance(bank, dict) or not isinstance(bank.get("inactive", {}), dict)
            or (bank.get("owner") is not None and not isinstance(bank["owner"], str))):
        raise ValueError(f"无法识别 Codex 账号状态结构，原文件未覆盖：{home}")
    if any(k.startswith("electron-account-renderer-state-") and k != ACCOUNT_STATE for k in state):
        raise ValueError("Codex 账号状态格式已更新，请先更新共享工作区适配")
    records = list(bank.get("inactive", {}).items())
    if bank.get("owner") is not None or ACCOUNT_STATE not in state:
        records.append((bank.get("owner", "legacy"), {"globals": state, "atoms": state.get(ATOMS, {})}))
    for account, snapshot in records:
        if not isinstance(snapshot, dict) or not all(isinstance(snapshot.get(k, {}), dict) for k in ("globals", "atoms")):
            raise ValueError(f"无法识别 Codex 账号快照，原文件未覆盖：{home}")
        key = json.dumps([str(home.resolve()), account], ensure_ascii=False)
        yield key, snapshot


def _root_key(project):
    paths = project.get("rootPaths")
    if not isinstance(paths, list) or not paths or not all(isinstance(p, str) and p for p in paths):
        raise ValueError("项目目录格式无法识别，共享工作区未覆盖原数据")
    return json.dumps(sorted({ntpath.normcase(ntpath.normpath(p.removeprefix("\\\\?\\"))) for p in paths}))


def _extract(snapshot, store):
    glob, atoms = snapshot.get("globals", {}), snapshot.get("atoms", {})
    projects, ids = {}, {}
    for project_id, value in glob.get("local-projects", {}).items():
        if not isinstance(value, dict) or not isinstance(value.get("name"), str):
            raise ValueError("项目结构无法识别，共享工作区未覆盖原数据")
        canonical = store["projectIds"].setdefault(_root_key(value), project_id)
        ids[project_id] = canonical
        # 云端绑定、权限与其他账号字段不能进入共享工作区。
        projects[canonical] = {k: deepcopy(value[k]) for k in ("name", "rootPaths", "createdAt", "updatedAt") if k in value}
        projects[canonical]["id"] = canonical

    def item_key(key):
        if key.startswith(PROJECT_PREFIX) and key[len(PROJECT_PREFIX):] in ids:
            return PROJECT_PREFIX + ids[key[len(PROJECT_PREFIX):]]
        if key.startswith(THREAD_PREFIX):
            return key
        return None

    order = [k[len(PROJECT_PREFIX):] for k in atoms.get("unified-sidebar-project-order-v1", []) if k.startswith(PROJECT_PREFIX)]
    order.extend(glob.get("project-order", list(ids)))
    pinned = ([k[len(PROJECT_PREFIX):] for k in atoms["unified-sidebar-pinned-order-v1"] if k.startswith(PROJECT_PREFIX)]
              if "unified-sidebar-pinned-order-v1" in atoms else glob.get("pinned-project-ids", []))
    sections, section_ids, section_order, collapsed = {}, {}, [], []
    for bucket in atoms.get(SECTIONS, {}).values():
        for section in bucket.get("sections", []):
            sid = section["id"]
            canonical = store["sectionIds"].get(sid)
            if canonical is None:
                canonical = next((s["id"] for s in store["workspace"].get("sections", {}).values()
                                  if s["name"] == section["name"]), sid)
                store["sectionIds"][sid] = canonical
            section_ids[sid] = canonical
            sections[canonical] = {
                "id": canonical, "name": section["name"], "appearance": deepcopy(section.get("appearance")),
                "itemKeys": list(dict.fromkeys(k for key in section.get("itemKeys", []) if (k := item_key(key)))),
            }
        section_order.extend("custom:" + section_ids[k[7:]] if k.startswith("custom:") and k[7:] in section_ids else k
                             for k in bucket.get("sectionOrder", []))
        collapsed.extend(section_ids[k] for k in bucket.get("collapsedSectionIds", []) if k in section_ids)
    return {
        "projects": projects,
        "projectOrder": list(dict.fromkeys(ids[k] for k in order if k in ids)),
        "appearances": {ids[k]: deepcopy(v) for k, v in glob.get("project-appearances", {}).items() if k in ids},
        "assignments": {k: {"projectKind": "local", "projectId": ids[v["projectId"]]}
                        for k, v in glob.get("thread-project-assignments", {}).items()
                        if v.get("projectKind") == "local" and v.get("projectId") in ids},
        "threadOrders": {ids[k]: deepcopy(v) for k, v in glob.get("sidebar-project-thread-orders", {}).items() if k in ids},
        "sections": sections, "sectionOrder": list(dict.fromkeys(section_order)),
        "collapsedSections": list(dict.fromkeys(collapsed)),
        "unassigned": list(glob.get("projectless-thread-ids", [])),
        "pinnedProjects": list(dict.fromkeys(ids[k] for k in pinned if k in ids)),
        "preferences": deepcopy(atoms.get("flat-project-sidebar-preferences-v1", {})),
    }


def _merge(base, local, shared):
    """只提交相对上次快照的变更，避免多开旧实例覆盖其他账号的更新。"""
    if local == base:
        return shared
    if local is _MISSING:
        return _MISSING if shared == base else shared
    if shared is _MISSING:
        return deepcopy(local)
    if isinstance(local, dict) and (base is _MISSING or isinstance(base, dict)):
        base = {} if base is _MISSING else base
        result = deepcopy(shared) if isinstance(shared, dict) else {}
        for key in dict.fromkeys([*base, *local]):
            value = _merge(base.get(key, _MISSING), local.get(key, _MISSING), result.get(key, _MISSING))
            if value is _MISSING:
                result.pop(key, None)
            else:
                result[key] = deepcopy(value)
        return result
    if isinstance(local, list):
        removed = [v for v in base if v not in local] if isinstance(base, list) else []
        return deepcopy(local + [v for v in shared if v not in local and v not in removed]) if isinstance(shared, list) else deepcopy(local)
    return deepcopy(local)


def _collect(store, records):
    # 完整快照优先确定稳定 ID；首次导入时，完整快照的布局优先。
    original_order = {key: i for i, (key, _) in enumerate(records)}
    first_import = not store["baselines"]
    records = sorted(records, key=lambda r: len(r[1].get("globals", {}).get("local-projects", {})), reverse=True)
    section_names = {s["name"]: sid for sid, s in store["workspace"].get("sections", {}).items()}
    extracted = []
    for key, record in records:
        for bucket in record.get("atoms", {}).get(SECTIONS, {}).values():
            for section in bucket.get("sections", []):
                store["sectionIds"].setdefault(section["id"], section_names.setdefault(section["name"], section["id"]))
        local = _extract(record, store)
        extracted.append((key, local))
    pending = list(reversed(extracted)) if first_import else sorted(extracted, key=lambda r: original_order[r[0]])
    for key, local in pending:
        base = store["baselines"].get(key, {})
        workspace = _merge(base, local, store["workspace"])
        assert isinstance(workspace, dict)
        for sid, section in local["sections"].items():
            previous = base.get("sections", {}).get(sid, {}).get("itemKeys", [])
            moved = [k for k in section["itemKeys"] if k not in previous]
            for other_id, other in workspace["sections"].items():
                if other_id != sid:
                    other["itemKeys"] = [k for k in other["itemKeys"] if k not in moved]
        store["workspace"] = workspace
        store["baselines"][key] = local
    workspace = store["workspace"]
    projects = workspace.get("projects", {})
    for key in ("appearances", "threadOrders"):
        workspace[key] = {k: v for k, v in workspace.get(key, {}).items() if k in projects}
    for thread, value in list(workspace.get("assignments", {}).items()):
        if value["projectId"] not in projects:
            del workspace["assignments"][thread]
            workspace.setdefault("unassigned", []).append(thread)
    for key in ("projectOrder", "pinnedProjects"):
        workspace[key] = [k for k in workspace.get(key, []) if k in projects]
    for section in workspace.get("sections", {}).values():
        section["itemKeys"] = [k for k in section["itemKeys"] if not k.startswith(PROJECT_PREFIX) or k[len(PROJECT_PREFIX):] in projects]


def _project_snapshot(snapshot, workspace, account, records, home):
    glob, atoms = snapshot.setdefault("globals", {}), snapshot.setdefault("atoms", {})
    old_projects = glob.get("local-projects", {})
    old_assignments = deepcopy(glob.get("thread-project-assignments", {}))
    projects = workspace.get("projects", {})
    glob["local-projects"] = {k: {**old_projects.get(k, {}), **deepcopy(v)} for k, v in projects.items()}
    glob["project-order"] = workspace.get("projectOrder", []) + [k for k in projects if k not in workspace.get("projectOrder", [])]
    for key, shared_key in (("project-appearances", "appearances"), ("sidebar-project-thread-orders", "threadOrders")):
        glob[key] = {**{k: v for k, v in glob.get(key, {}).items() if k not in old_projects}, **deepcopy(workspace.get(shared_key, {}))}
    glob["pinned-project-ids"] = deepcopy(workspace.get("pinnedProjects", []))
    assignments = glob.get("thread-project-assignments", {})
    glob["thread-project-assignments"] = {
        **{k: v for k, v in assignments.items() if v.get("projectKind") != "local"},
        **deepcopy(workspace.get("assignments", {})),
    }
    glob["thread-project-membership-host-ids"] = {
        **glob.get("thread-project-membership-host-ids", {}), **{k: "local" for k in workspace.get("assignments", {})},
    }
    glob["projectless-thread-ids"] = [k for k in workspace.get("unassigned", []) if k not in glob["thread-project-assignments"]]
    selected = glob.get("selected-project")
    if isinstance(selected, dict) and selected.get("type") == "local" and selected.get("projectId") not in projects:
        glob.pop("selected-project", None)

    # App Server 的 ID 属于具体 CodexHome，只复用同一目录的已有映射。
    mappings = glob.setdefault(SERVER_IDS, {})
    for _, record in records:
        for host, values in list(record.get("globals", {}).get(SERVER_IDS, {}).items()):
            if host.startswith("local:") and Path(host[6:]).resolve() == home.resolve():
                mappings[host] = {**values, **mappings.get(host, {})}
                canonical_host = "local:" + str(home)
                mappings[canonical_host] = {**values, **mappings.get(canonical_host, {})}
    host = "local:" + str(home)
    if old_projects != glob["local-projects"] or old_assignments != glob["thread-project-assignments"]:
        glob.setdefault(MIGRATIONS, {})[host] = {"version": 1, "projectsMigrated": False, "threadAssignmentsMigrated": False}

    old_bucket = atoms.get(SECTIONS, {}).get(account, {})
    old_sections = old_bucket.get("sections", [])
    home_sections = [s for _, record in records for bucket in record.get("atoms", {}).get(SECTIONS, {}).values()
                     for s in bucket.get("sections", [])]
    sections = []
    for sid, section in workspace.get("sections", {}).items():
        old = next((s for s in old_sections if s["id"] == sid or s["name"] == section["name"]), {})
        foreign = [k for k in old.get("itemKeys", []) if not k.startswith((PROJECT_PREFIX, THREAD_PREFIX))]
        result = {**deepcopy(old), **deepcopy(section), "itemKeys": section["itemKeys"] + foreign}
        if "pendingDeletionHostIdsByItemKey" in result:
            result["pendingDeletionHostIdsByItemKey"] = {k: v for k, v in result["pendingDeletionHostIdsByItemKey"].items() if k in foreign}
        replica = next((s for s in [old, *home_sections]
                        if (s.get("id") == sid or s.get("name") == section["name"]) and s.get("hostSectionIds", {}).get("local")), {})
        if replica:
            result["hostSectionIds"] = {**result.get("hostSectionIds", {}), "local": replica["hostSectionIds"]["local"]}
        sections.append(result)
    for old in old_sections:
        foreign = [k for k in old.get("itemKeys", []) if not k.startswith((PROJECT_PREFIX, THREAD_PREFIX))]
        if foreign and not any(s["id"] == old["id"] or s["name"] == old["name"] for s in sections):
            sections.append({**old, "itemKeys": foreign})
    valid_sections = {s["id"] for s in sections}
    order = [k for k in workspace.get("sectionOrder", []) if not k.startswith("custom:") or k[7:] in valid_sections]
    order.extend("custom:" + s["id"] for s in sections if "custom:" + s["id"] not in order)
    atoms.setdefault(SECTIONS, {})[account] = {
        **old_bucket,
        "sections": sections, "sectionOrder": order,
        "collapsedSectionIds": [k for k in workspace.get("collapsedSections", []) if k in valid_sections],
        "appServerMigratedHostIds": old_bucket.get("appServerMigratedHostIds", []) if sections == old_sections else [],
        "appServerLegacySectionIds": [k for k in old_bucket.get("appServerLegacySectionIds", []) if k in valid_sections],
    }
    atoms["flat-project-sidebar-preferences-v1"] = deepcopy(workspace.get("preferences", {}))
    atoms["unified-sidebar-project-order-v1"] = [PROJECT_PREFIX + k for k in glob["project-order"]] + [
        k for k in atoms.get("unified-sidebar-project-order-v1", []) if not k.startswith(PROJECT_PREFIX)
    ]
    atoms["unified-sidebar-pinned-order-v1"] = [PROJECT_PREFIX + k for k in glob["pinned-project-ids"]] + [
        k for k in atoms.get("unified-sidebar-pinned-order-v1", []) if not k.startswith(PROJECT_PREFIX)
    ]


def _atomic_write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def sync_shared_workspace(shared_path, source_homes, *, target_home=None, auth_path=None):
    """汇总已落盘的增量；提供 target_home 时准备下次启动使用的账号快照。"""
    shared_path = Path(shared_path)
    identity = _identity(auth_path) if target_home is not None and auth_path is not None else None
    target_home = Path(target_home).resolve() if target_home is not None else None
    homes = list(dict.fromkeys(Path(p).resolve() for p in [*source_homes, *([target_home] if target_home else [])]))
    shared_path.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_file_lock(shared_path.with_suffix(".lock"), timeout_seconds=30):
        original_store = _read_json(shared_path)
        if original_store and original_store.get("version") != 1:
            raise ValueError("共享工作区版本无法识别，原文件未覆盖")
        store = deepcopy(original_store) if original_store else {
            "version": 1, "workspace": {}, "projectIds": {}, "sectionIds": {}, "baselines": {},
        }
        states = {p: _read_json(p / STATE_FILE) for p in homes}
        homes.sort(key=lambda p: (p / STATE_FILE).stat().st_mtime_ns if (p / STATE_FILE).exists() else 0)
        records_by_home = {p: list(_records(p, state)) for p, state in states.items()}
        _collect(store, [r for records in records_by_home.values() for r in records])
        backup_dir = None

        def save(path, value):
            nonlocal backup_dir
            if path.exists():
                try:
                    if _read_json(path) == value:
                        return
                except ValueError:
                    if target_home is None or path != target_home / (STATE_FILE + ".bak"):
                        raise
            if backup_dir is None:
                backup_dir = shared_path.parent / "backups" / "shared-workspace" / f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"
                backup_dir.mkdir(parents=True)
                sources = [shared_path, *[p / STATE_FILE for p in homes]]
                if target_home:
                    sources.append(target_home / (STATE_FILE + ".bak"))
                manifest = {}
                for source in sources:
                    if source.exists():
                        name = hashlib.sha256(str(source).encode()).hexdigest()[:16] + ".bak"
                        (backup_dir / name).write_bytes(source.read_bytes())
                        manifest[name] = str(source)
                _atomic_write(backup_dir / "manifest.json", manifest)
            _atomic_write(path, value)

        # 先提交共享数据；投影失败时仍保留已汇总的数据和原账号的检查点。
        save(shared_path, store)
        if target_home is not None and identity is not None:
            state = states[target_home]
            next_owner, account = identity
            bank = state.setdefault(ACCOUNT_STATE, {"owner": None, "inactive": {}})
            active = bank.get("owner") == next_owner
            snapshot = ({"globals": state, "atoms": state.setdefault(ATOMS, {})} if active
                        else bank.setdefault("inactive", {}).setdefault(next_owner, {"globals": {}, "atoms": {}}))
            _project_snapshot(snapshot, store["workspace"], account, records_by_home[target_home], target_home)
            save(target_home / STATE_FILE, state)
            save(target_home / (STATE_FILE + ".bak"), state)
            key = json.dumps([str(target_home), next_owner], ensure_ascii=False)
            store["baselines"][key] = _extract(snapshot, store)
            save(shared_path, store)
        return {
            "projectCount": len(store["workspace"].get("projects", {})),
            "sectionCount": len(store["workspace"].get("sections", {})),
            "sharedPath": str(shared_path), "backupPath": str(backup_dir) if backup_dir else "",
        }
