import json
import os
import shutil
import sqlite3
import subprocess
from pathlib import Path

from core.constants import (
    DEFAULT_PROFILE_ROOT,
    DEFAULT_SESSION_SYNC_ROOT,
    MEMORY_SYNC_DB_NAME,
    MEMORY_SYNC_SIDECAR_NAMES,
    MEMORY_SYNC_TABLE_NAMES,
    PROJECT_CONFIG_SECTION_RE,
    SESSION_SYNC_DIR_NAMES,
    SESSION_SYNC_FILE_NAMES,
    SESSION_SYNC_STATE_DB_NAME,
    SESSION_SYNC_STATE_SIDECAR_NAMES,
    SESSION_SYNC_STATE_TABLE_NAMES,
    TOML_SECTION_RE,
)
from core.path_utils import (
    is_reparse_point,
    normalize_cap_sid_project_path,
    normalize_project_config_path,
    sanitize_profile_name,
)


def prepare_session_sync(config, codex_home_dir):
    """把账号 CodexHome 中的会话白名单路径同步到共享目录。"""
    if not config.get("session_sync_enabled", False):
        return

    sync_root = get_session_sync_root(config)
    sync_root.mkdir(parents=True, exist_ok=True)
    for directory_name in SESSION_SYNC_DIR_NAMES:
        prepare_shared_directory(codex_home_dir / directory_name, sync_root / directory_name)
    for file_name in SESSION_SYNC_FILE_NAMES:
        prepare_shared_file(codex_home_dir / file_name, sync_root / file_name)
    prepare_shared_state_database(codex_home_dir, sync_root)
    prepare_project_config_sync(config, codex_home_dir)
    prepare_project_cap_sid_sync(config, codex_home_dir)


def prepare_memory_sync(config, codex_home_dir):
    """合并 Codex 记忆数据库，并写回当前账号本地数据库。"""
    if not config.get("memory_sync_enabled", False):
        return

    sync_root = get_session_sync_root(config)
    sync_root.mkdir(parents=True, exist_ok=True)
    shared_path = sync_root / MEMORY_SYNC_DB_NAME

    if shared_path.exists() and not is_sqlite_database_healthy(shared_path):
        quarantine_sqlite_database_files(
            sync_root,
            MEMORY_SYNC_DB_NAME,
            MEMORY_SYNC_SIDECAR_NAMES,
            "corrupt-before-memory-sync",
        )

    local_candidates = find_healthy_memory_databases(codex_home_dir)
    for local_candidate in local_candidates:
        if shared_path.exists():
            merge_sqlite_tables(local_candidate, shared_path, MEMORY_SYNC_TABLE_NAMES)
        else:
            copy_sqlite_database(local_candidate, shared_path)

    if shared_path.exists() and not is_sqlite_database_healthy(shared_path):
        quarantine_sqlite_database_files(
            sync_root,
            MEMORY_SYNC_DB_NAME,
            MEMORY_SYNC_SIDECAR_NAMES,
            "corrupt-before-memory-sync",
        )

    if not shared_path.exists():
        return

    checkpoint_sqlite_database(shared_path)
    replace_local_sqlite_database(codex_home_dir, shared_path, MEMORY_SYNC_DB_NAME, MEMORY_SYNC_SIDECAR_NAMES)
    sqlite_dir = codex_home_dir / "sqlite"
    if sqlite_dir.exists():
        replace_local_sqlite_database(sqlite_dir, shared_path, MEMORY_SYNC_DB_NAME, MEMORY_SYNC_SIDECAR_NAMES)


def find_healthy_memory_databases(codex_home_dir):
    """查找可用于合并的健康记忆数据库。"""
    candidates = [
        codex_home_dir / MEMORY_SYNC_DB_NAME,
        codex_home_dir / "sqlite" / MEMORY_SYNC_DB_NAME,
    ]
    candidates.extend(sorted(codex_home_dir.glob(f"{MEMORY_SYNC_DB_NAME}.local-before-memory-sync*")))
    healthy = []
    seen = set()
    for candidate in candidates:
        if candidate in seen or candidate.is_symlink():
            continue
        seen.add(candidate)
        if candidate.is_file() and is_sqlite_database_healthy(candidate):
            healthy.append(candidate)
    return healthy


def get_session_sync_root(config):
    """读取会话共享目录，兼容旧配置缺失的情况。"""
    configured_root = config.get("session_sync_root") or str(DEFAULT_SESSION_SYNC_ROOT)
    return Path(configured_root)


def get_profile_dir(config, profile_name):
    """按启动器配置计算账号目录，避免同步服务反向依赖桥接层。"""
    profile_root = Path(config.get("profile_root") or DEFAULT_PROFILE_ROOT)
    return profile_root / sanitize_profile_name(profile_name)


def prepare_shared_directory(local_path, shared_path):
    """合并已有本地目录后，用目录联接指向共享目录。"""
    shared_path.mkdir(parents=True, exist_ok=True)
    if is_linked_to_shared_path(local_path, shared_path):
        return

    if local_path.exists():
        if local_path.is_dir():
            copy_directory(local_path, shared_path)
        backup_path = next_sync_backup_path(local_path)
        local_path.rename(backup_path)

    local_path.parent.mkdir(parents=True, exist_ok=True)
    create_directory_junction(local_path, shared_path)


def copy_directory(source_dir, target_dir):
    """把本地会话目录合并到共享目录，并跳过联接目录。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    for root, dirs, files in os.walk(source_dir):
        root_path = Path(root)
        relative_root = root_path.relative_to(source_dir)
        target_root = target_dir / relative_root
        target_root.mkdir(parents=True, exist_ok=True)
        kept_dirs = []
        for directory_name in dirs:
            source_child = root_path / directory_name
            if is_reparse_point(source_child):
                continue
            kept_dirs.append(directory_name)
            (target_root / directory_name).mkdir(parents=True, exist_ok=True)
        dirs[:] = kept_dirs
        for file_name in files:
            source_file = root_path / file_name
            if is_reparse_point(source_file):
                continue
            target_file = target_root / file_name
            if target_file.exists():
                continue
            shutil.copy2(source_file, target_file)


def prepare_shared_file(local_path, shared_path):
    """合并已有本地文本文件后，用文件符号链接指向共享文件。"""
    shared_path.parent.mkdir(parents=True, exist_ok=True)
    if local_path.exists() and local_path.is_file():
        if shared_path.exists():
            merge_text_lines(local_path, shared_path)
        else:
            shutil.copy2(local_path, shared_path)
    if not shared_path.exists():
        shared_path.write_text("", encoding="utf-8")
    if is_linked_to_shared_path(local_path, shared_path):
        return

    if local_path.exists():
        backup_path = next_sync_backup_path(local_path)
        local_path.rename(backup_path)

    local_path.parent.mkdir(parents=True, exist_ok=True)
    create_file_symlink(local_path, shared_path)


def merge_text_lines(source_path, target_path):
    """把本地文本行合并进共享文件，保留已有顺序并去重。"""
    try:
        existing_lines = target_path.read_text(encoding="utf-8").splitlines()
        source_lines = source_path.read_text(encoding="utf-8").splitlines()
    except UnicodeDecodeError:
        return
    seen = set(existing_lines)
    merged_lines = list(existing_lines)
    for line in source_lines:
        if line in seen:
            continue
        merged_lines.append(line)
        seen.add(line)
    target_path.write_text("\n".join(merged_lines) + ("\n" if merged_lines else ""), encoding="utf-8")


def prepare_project_config_sync(config, codex_home_dir):
    """把所有账号配置里的项目白名单合并到当前账号。"""
    target_config_path = codex_home_dir / "config.toml"
    project_sections = collect_project_config_sections(config)
    if not project_sections:
        return

    current_text = ""
    if target_config_path.exists():
        current_text = target_config_path.read_text(encoding="utf-8")

    existing_keys = extract_project_config_keys(current_text)
    missing_sections = [
        section_text
        for project_key, section_text in project_sections.items()
        if project_key not in existing_keys
    ]
    updated_text = current_text
    if missing_sections:
        separator = "\n\n" if current_text and not current_text.endswith("\n\n") else ""
        updated_text = current_text + separator + "\n\n".join(missing_sections) + "\n"
    updated_text = ensure_desktop_project_list_enabled(updated_text)

    if updated_text == current_text:
        return

    if target_config_path.exists():
        backup_file_once(target_config_path, "local-before-project-sync")
    target_config_path.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(target_config_path, updated_text)


def ensure_desktop_project_list_enabled(text):
    """同步会话时打开项目侧栏依赖的桌面项目建议开关。"""
    lines = text.splitlines()
    desktop_index = find_toml_section_index(lines, "desktop")
    if desktop_index is None:
        return text.rstrip() + "\n\n[desktop]\nambient-suggestions-enabled = true\n"

    section_end = find_toml_section_end(lines, desktop_index + 1)
    for index in range(desktop_index + 1, section_end):
        if lines[index].strip().startswith("ambient-suggestions-enabled"):
            lines[index] = "ambient-suggestions-enabled = true"
            return "\n".join(lines).rstrip() + "\n"

    lines.insert(section_end, "ambient-suggestions-enabled = true")
    return "\n".join(lines).rstrip() + "\n"


def find_toml_section_index(lines, section_name):
    """查找指定配置顶层段。"""
    section_header = f"[{section_name}]"
    for index, line in enumerate(lines):
        if line.strip() == section_header:
            return index
    return None


def find_toml_section_end(lines, start_index):
    """查找配置段结束位置。"""
    index = start_index
    while index < len(lines):
        if TOML_SECTION_RE.match(lines[index].strip()):
            return index
        index += 1
    return len(lines)


def collect_project_config_sections(config):
    """从所有账号配置收集项目段。"""
    sections = {}
    for config_path in iter_profile_config_paths(config):
        if not config_path.exists():
            continue
        try:
            text = config_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for project_key, section_text in extract_project_config_sections(text).items():
            sections.setdefault(project_key, section_text)
    return sections


def iter_profile_config_paths(config):
    """遍历所有账号的项目配置文件。"""
    for profile_name in config.get("profiles", []):
        yield get_profile_dir(config, profile_name) / "CodexHome" / "config.toml"


def extract_project_config_sections(text):
    """提取项目配置段。"""
    lines = text.splitlines()
    sections = {}
    index = 0
    while index < len(lines):
        header_match = PROJECT_CONFIG_SECTION_RE.match(lines[index].strip())
        if not header_match:
            index += 1
            continue

        start_index = index
        index += 1
        while index < len(lines) and not TOML_SECTION_RE.match(lines[index].strip()):
            index += 1

        project_key = normalize_project_config_path(header_match.group("path"))
        section_text = "\n".join(lines[start_index:index]).strip()
        if section_text:
            sections.setdefault(project_key, section_text)
    return sections


def extract_project_config_keys(text):
    """提取已有项目路径键。"""
    return set(extract_project_config_sections(text).keys())


def backup_file_once(path, suffix):
    """为文件创建一次性备份。"""
    backup_path = path.with_name(f"{path.name}.{suffix}")
    if backup_path.exists():
        return
    shutil.copy2(path, backup_path)


def write_text_atomic(path, text):
    """原子写入文本文件。"""
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    os.replace(temp_path, path)


def prepare_project_cap_sid_sync(config, codex_home_dir):
    """只合并 cap_sid 中的 workspace_by_cwd 工作区注册表。"""
    merged_workspace_by_cwd = collect_workspace_by_cwd_entries(config)
    if not merged_workspace_by_cwd:
        return

    target_path = codex_home_dir / "cap_sid"
    target_data = read_cap_sid_file(target_path)
    if not target_data:
        target_data = {
            "workspace": "",
            "readonly": "",
            "workspace_by_cwd": {},
            "writable_root_by_path": {},
        }

    target_workspace_by_cwd = target_data.setdefault("workspace_by_cwd", {})
    changed = False
    for project_path, sid in merged_workspace_by_cwd.items():
        if project_path in target_workspace_by_cwd:
            continue
        target_workspace_by_cwd[project_path] = sid
        changed = True

    if not changed:
        return

    if target_path.exists():
        backup_file_once(target_path, "local-before-project-sync")
    write_json_atomic(target_path, target_data)


def collect_workspace_by_cwd_entries(config):
    """从所有账号的 cap_sid 收集工作区注册表。"""
    entries = {}
    for cap_sid_path in iter_profile_cap_sid_paths(config):
        data = read_cap_sid_file(cap_sid_path)
        workspace_by_cwd = data.get("workspace_by_cwd", {}) if data else {}
        if not isinstance(workspace_by_cwd, dict):
            continue
        for project_path, sid in workspace_by_cwd.items():
            if not isinstance(project_path, str) or not isinstance(sid, str):
                continue
            entries.setdefault(normalize_cap_sid_project_path(project_path), sid)
    return entries


def iter_profile_cap_sid_paths(config):
    """遍历所有账号的 cap_sid 文件。"""
    for profile_name in config.get("profiles", []):
        yield get_profile_dir(config, profile_name) / "CodexHome" / "cap_sid"


def read_cap_sid_file(path):
    """读取 cap_sid 文件，不可读时返回空字典。"""
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def write_json_atomic(path, data):
    """原子写入 JSON 文件。"""
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    os.replace(temp_path, path)


def prepare_shared_state_database(codex_home_dir, sync_root):
    """合并桌面端会话侧栏状态库，并写回本地真实文件。"""
    local_path = codex_home_dir / SESSION_SYNC_STATE_DB_NAME
    shared_path = sync_root / SESSION_SYNC_STATE_DB_NAME

    if shared_path.exists() and not is_sqlite_database_healthy(shared_path):
        quarantine_state_database_files(sync_root, "corrupt-before-sync")

    local_candidate = find_healthy_state_database(codex_home_dir)
    if local_candidate:
        if shared_path.exists():
            merge_state_database(local_candidate, shared_path)
        else:
            copy_sqlite_database(local_candidate, shared_path)
    elif local_path.exists() or local_path.is_symlink():
        quarantine_state_database_files(codex_home_dir, "corrupt-before-sync")

    if shared_path.exists() and not is_sqlite_database_healthy(shared_path):
        quarantine_state_database_files(sync_root, "corrupt-before-sync")

    if not shared_path.exists():
        remove_local_state_database_files(codex_home_dir)
        return

    checkpoint_sqlite_database(shared_path)
    replace_local_state_database(codex_home_dir, shared_path)


def find_healthy_state_database(codex_home_dir):
    """查找可用于恢复共享状态库的健康本地状态库。"""
    candidates = [codex_home_dir / SESSION_SYNC_STATE_DB_NAME]
    candidates.extend(sorted(codex_home_dir.glob(f"{SESSION_SYNC_STATE_DB_NAME}.local-before-sync*")))
    candidates.extend(sorted(codex_home_dir.glob(f"{SESSION_SYNC_STATE_DB_NAME}.corrupt-before-sync*")))
    for candidate in candidates:
        if candidate.is_symlink():
            continue
        if candidate.is_file() and is_sqlite_database_healthy(candidate):
            return candidate
    return None


def is_sqlite_database_healthy(database_path):
    """检查数据库文件是否可读且完整。"""
    if not database_path.exists():
        return False
    try:
        connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()
            return result is not None and result[0] == "ok"
        finally:
            connection.close()
    except sqlite3.DatabaseError:
        return False
    except OSError:
        return False


def quarantine_state_database_files(directory, suffix):
    """隔离损坏或旧版链接产生的状态库文件。"""
    quarantine_sqlite_database_files(
        directory,
        SESSION_SYNC_STATE_DB_NAME,
        SESSION_SYNC_STATE_SIDECAR_NAMES,
        suffix,
    )


def quarantine_sqlite_database_files(directory, database_name, sidecar_names, suffix):
    """隔离指定数据库及其旁路文件。"""
    for file_name in (database_name, *sidecar_names):
        path = directory / file_name
        if not path.exists() and not path.is_symlink():
            continue
        quarantine_path = next_named_backup_path(path, suffix)
        path.rename(quarantine_path)


def next_named_backup_path(path, suffix):
    """生成指定后缀的备份路径。"""
    candidate = path.with_name(f"{path.name}.{suffix}")
    index = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f"{path.name}.{suffix}.{index}")
        index += 1
    return candidate


def merge_state_database(source_path, target_path):
    """把本地会话索引表合并进共享状态库。"""
    merge_sqlite_tables(source_path, target_path, SESSION_SYNC_STATE_TABLE_NAMES)


def merge_sqlite_tables(source_path, target_path, table_names):
    """把指定数据库表按主键忽略冲突地合并进目标库。"""
    source_connection = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target_connection = sqlite3.connect(target_path)
    try:
        for table_name in table_names:
            merge_sqlite_table(source_connection, target_connection, table_name)
        target_connection.commit()
    finally:
        source_connection.close()
        target_connection.close()


def checkpoint_sqlite_database(database_path):
    """尽量把预写日志内容刷回主库，便于复制本地快照。"""
    connection = sqlite3.connect(database_path)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()


def copy_sqlite_database(source_path, target_path):
    """使用数据库备份接口复制一致快照，避免遗漏预写日志内容。"""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(f".{target_path.name}.sync-tmp")
    if temp_path.exists():
        temp_path.unlink()
    source_connection = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
    target_connection = sqlite3.connect(temp_path)
    try:
        source_connection.backup(target_connection)
        target_connection.commit()
    finally:
        source_connection.close()
        target_connection.close()
    os.replace(temp_path, target_path)


def merge_sqlite_table(source_connection, target_connection, table_name):
    """按主键忽略冲突地合并一个数据库表。"""
    if not sqlite_table_exists(source_connection, table_name):
        return
    if not sqlite_table_exists(target_connection, table_name):
        return
    column_names = [
        row[1]
        for row in source_connection.execute(f"PRAGMA table_info({table_name})").fetchall()
    ]
    if not column_names:
        return
    quoted_columns = ", ".join(f'"{column_name}"' for column_name in column_names)
    placeholders = ", ".join("?" for _ in column_names)
    insert_sql = f'INSERT OR IGNORE INTO "{table_name}" ({quoted_columns}) VALUES ({placeholders})'
    rows = source_connection.execute(f'SELECT {quoted_columns} FROM "{table_name}"').fetchall()
    target_connection.executemany(insert_sql, rows)


def sqlite_table_exists(connection, table_name):
    """检查数据库表是否存在。"""
    row = connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def replace_local_state_database(codex_home_dir, shared_path):
    """用共享状态库快照替换当前账号本地状态库。"""
    replace_local_sqlite_database(
        codex_home_dir,
        shared_path,
        SESSION_SYNC_STATE_DB_NAME,
        SESSION_SYNC_STATE_SIDECAR_NAMES,
    )


def replace_local_sqlite_database(directory, shared_path, database_name, sidecar_names):
    """替换本地数据库主文件，并清理旁路文件。"""
    directory.mkdir(parents=True, exist_ok=True)
    remove_local_sqlite_database_files(directory, database_name, sidecar_names)
    local_path = directory / database_name
    temp_path = local_path.with_name(f".{local_path.name}.sync-copy")
    copy_sqlite_database(shared_path, temp_path)
    os.replace(temp_path, local_path)


def remove_local_state_database_files(codex_home_dir):
    """移除当前账号本地状态库及旁路文件。"""
    remove_local_sqlite_database_files(
        codex_home_dir,
        SESSION_SYNC_STATE_DB_NAME,
        SESSION_SYNC_STATE_SIDECAR_NAMES,
    )


def remove_local_sqlite_database_files(directory, database_name, sidecar_names):
    """删除本地数据库主文件和旁路文件。"""
    for file_name in (database_name, *sidecar_names):
        local_path = directory / file_name
        if local_path.exists() or local_path.is_symlink():
            if local_path.is_dir():
                shutil.rmtree(local_path)
            else:
                local_path.unlink()


def is_linked_to_shared_path(local_path, shared_path):
    """判断本地路径是否已经指向共享路径。"""
    if not local_path.exists() and not local_path.is_symlink():
        return False
    try:
        return local_path.resolve() == shared_path.resolve()
    except OSError:
        return False


def next_sync_backup_path(path):
    """生成会话同步替换前的备份路径。"""
    base_name = f"{path.name}.local-before-sync"
    candidate = path.with_name(base_name)
    index = 1
    while candidate.exists() or candidate.is_symlink():
        candidate = path.with_name(f"{base_name}.{index}")
        index += 1
    return candidate


def create_directory_junction(link_path, target_path):
    """创建目录联接，失败时抛出清晰错误。"""
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "无法创建目录联接")


def create_file_symlink(link_path, target_path):
    """创建文件符号链接，失败时抛出清晰错误。"""
    result = subprocess.run(
        ["cmd", "/c", "mklink", str(link_path), str(target_path)],
        capture_output=True,
        text=True,
        timeout=10,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "无法创建文件符号链接")
