import os
import shutil
import subprocess
from pathlib import Path

from core.codex_source import (
    find_running_codex_path,
    find_windowsapps_codex_path,
    get_file_version,
    portable_app_needs_update,
    prepare_portable_codex_path,
    read_running_codex_commands,
    read_running_codex_processes,
)
from core.config_store import load_config, save_config
from core.constants import (
    CONFIG_LAST_GOOD_PATH,
    CONFIG_PATH,
    CONFIG_PREVIOUS_GOOD_PATH,
    DEFAULT_CODEX_ENV_PATH,
    DEFAULT_PROFILE_ROOT,
    DEFAULT_SESSION_SYNC_ROOT,
    MEMORY_SYNC_DB_NAME,
    PORTABLE_APP_DIR_NAME,
)
from core.path_utils import (
    check_directory_writable,
    format_health_status,
    is_reparse_point,
    normalize_path_for_match,
    remove_readonly_path,
    sanitize_profile_name,
)
from core.profile_service import ensure_profile_env_file
from core.sync_service import prepare_memory_sync, prepare_session_sync
from core.usage_service import (
    get_cached_profile_usage,
    refresh_all_profile_usage as refresh_all_profile_usage_cache,
    refresh_profile_usage as refresh_profile_usage_cache,
    remove_cached_usage,
    rename_cached_usage,
)


def ok(data=None):
    """生成统一成功响应，供 Electron 界面稳定解析。"""
    return {"ok": True, "data": data or {}, "error": ""}


def fail(message):
    """生成统一失败响应，避免把异常对象直接泄露给界面。"""
    return {"ok": False, "data": {}, "error": str(message)}


def invoke(command, payload=None):
    """按白名单分发桥接命令。"""
    payload = payload or {}
    commands = {
        "create_profile": create_profile,
        "delete_profile": delete_profile,
        "get_app_state": get_app_state,
        "get_diagnostics": get_diagnostics,
        "launch_profile": launch_profile,
        "list_profiles": list_profiles,
        "refresh_codex_source": refresh_codex_source,
        "refresh_all_profile_usage": refresh_all_profile_usage,
        "refresh_profile_usage": refresh_profile_usage,
        "rename_profile": rename_profile,
        "open_session_sync_dir": open_session_sync_dir,
        "set_codex_path": set_codex_path,
        "set_memory_sync": set_memory_sync,
        "set_profile_root": set_profile_root,
        "set_session_sync": set_session_sync,
        "open_path": open_path,
        "stop_profile": stop_profile,
    }
    handler = commands.get(command)
    if not handler:
        return fail(f"未知命令：{command}")
    try:
        return ok(handler(payload))
    except Exception as exc:
        return fail(exc)


def get_app_state(_payload=None):
    """读取新界面首页需要的基础状态。"""
    config = load_config()
    codex_path = config.get("codex_path", "")
    profiles = config.get("profiles", [])
    profile_root = Path(config.get("profile_root") or DEFAULT_PROFILE_ROOT)
    session_sync_root = Path(config.get("session_sync_root") or DEFAULT_SESSION_SYNC_ROOT)
    running_commands = read_running_codex_commands()
    return {
        "codexPath": codex_path,
        "codexExists": bool(codex_path and Path(codex_path).exists()),
        "codexVersion": get_file_version(codex_path) if codex_path and Path(codex_path).exists() else "",
        "profileRoot": str(profile_root),
        "profileRootExists": profile_root.exists(),
        "profileCount": len(profiles),
        "runningCount": sum(1 for profile_name in profiles if _is_profile_running(config, profile_name, running_commands)),
        "sessionSyncEnabled": bool(config.get("session_sync_enabled", False)),
        "sessionSyncRoot": str(session_sync_root),
        "memorySyncEnabled": bool(config.get("memory_sync_enabled", False)),
        "memorySyncDatabase": str(session_sync_root / MEMORY_SYNC_DB_NAME),
    }


def list_profiles(_payload=None):
    """读取账号列表和每个账号的关键路径状态。"""
    config = load_config()
    running_commands = read_running_codex_commands()
    return {
        "profiles": [
            _build_profile_summary(config, profile_name, running_commands)
            for profile_name in config.get("profiles", [])
        ]
    }


def create_profile(payload):
    """新增账号并准备独立程序副本。"""
    name = _validate_profile_name(load_config(), payload.get("name", ""))
    config = load_config()
    profile_dir = _get_profile_dir(config, name)
    codex_path = _require_codex_path(config)
    ensure_profile_env_file(profile_dir / "CodexHome")
    prepare_portable_codex_path(codex_path, profile_dir)
    profiles = config.setdefault("profiles", [])
    profiles.append(name)
    save_config(config)
    return _build_profile_summary(config, name, read_running_codex_commands())


def rename_profile(payload):
    """修改账号名称，并同步移动对应目录。"""
    old_name = payload.get("oldName", "")
    config = load_config()
    if old_name not in config.get("profiles", []):
        raise ValueError("账号不存在")
    new_name = _validate_profile_name(config, payload.get("newName", ""), exclude_name=old_name)
    old_dir = _get_profile_dir(config, old_name)
    new_dir = _get_profile_dir(config, new_name)
    if old_dir.exists() and old_dir != new_dir:
        if new_dir.exists():
            raise FileExistsError(new_dir)
        old_dir.rename(new_dir)
    profiles = config.setdefault("profiles", [])
    profiles[profiles.index(old_name)] = new_name
    if config.get("imported_original_profile") == old_name:
        config["imported_original_profile"] = new_name
    rename_cached_usage(old_name, new_name)
    save_config(config)
    return _build_profile_summary(config, new_name, read_running_codex_commands())


def delete_profile(payload):
    """删除账号配置和账号目录。"""
    name = payload.get("name", "")
    config = load_config()
    profiles = config.setdefault("profiles", [])
    if name not in profiles:
        raise ValueError("账号不存在")
    running_commands = read_running_codex_commands()
    if _is_profile_running(config, name, running_commands):
        raise RuntimeError("该账号正在运行，请先关闭对应 Codex 窗口")
    profile_dir = _get_profile_dir(config, name)
    if profile_dir.exists():
        shutil.rmtree(profile_dir)
    profiles.remove(name)
    if config.get("imported_original_profile") == name:
        config["imported_original_profile"] = ""
    remove_cached_usage(name)
    save_config(config)
    return {"name": name}


def launch_profile(payload):
    """按账号隔离环境变量后启动 Codex 桌面端。"""
    name = payload.get("name", "")
    config = load_config()
    if name not in config.get("profiles", []):
        raise ValueError("账号不存在")
    codex_path = _require_codex_path(config)
    profile_dir = _get_profile_dir(config, name)
    appdata_dir = profile_dir / "AppData" / "Roaming"
    localappdata_dir = profile_dir / "AppData" / "Local"
    codex_home_dir = profile_dir / "CodexHome"
    user_data_dir = _get_user_data_dir(config, name)
    target_app_dir = profile_dir / PORTABLE_APP_DIR_NAME
    running_commands = read_running_codex_commands()
    if _is_profile_running(config, name, running_commands) and portable_app_needs_update(codex_path, target_app_dir):
        raise RuntimeError("微软商店版 Codex 已更新，请先关闭该账号窗口后再启动")

    for directory in (appdata_dir, localappdata_dir, codex_home_dir, user_data_dir):
        directory.mkdir(parents=True, exist_ok=True)
    ensure_profile_env_file(codex_home_dir)

    env = os.environ.copy()
    env["APPDATA"] = str(appdata_dir)
    env["LOCALAPPDATA"] = str(localappdata_dir)
    env["CODEX_HOME"] = str(codex_home_dir)
    env["CODEX_MULTI_PROFILE"] = name

    portable_codex_path = prepare_portable_codex_path(codex_path, profile_dir)
    prepare_session_sync(config, codex_home_dir)
    prepare_memory_sync(config, codex_home_dir)
    subprocess.Popen(
        [portable_codex_path, f"--user-data-dir={user_data_dir}"],
        cwd=str(Path(portable_codex_path).parent),
        env=env,
        close_fds=True,
    )
    return {"name": name}


def stop_profile(payload):
    """关闭指定账号对应的 Codex 进程。"""
    name = payload.get("name", "")
    config = load_config()
    if name not in config.get("profiles", []):
        raise ValueError("账号不存在")
    match_targets = _get_profile_running_match_targets(config, name)
    matched_pids = [
        process["pid"]
        for process in read_running_codex_processes()
        if any(target in normalize_path_for_match(process["command_line"]) for target in match_targets)
    ]
    if not matched_pids:
        return {"name": name, "stopped": 0}
    for pid in matched_pids:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    return {"name": name, "stopped": len(matched_pids)}


def set_codex_path(payload):
    """保存用户选择的 Codex 程序路径。"""
    codex_path = payload.get("codexPath", "")
    if codex_path and not Path(codex_path).exists():
        raise FileNotFoundError(codex_path)
    config = load_config()
    config["codex_path"] = codex_path
    save_config(config)
    return {"codexPath": codex_path}


def refresh_codex_source(_payload=None):
    """重新识别微软商店版 Codex 路径并保存。"""
    codex_path = find_windowsapps_codex_path() or find_running_codex_path()
    if not codex_path:
        raise FileNotFoundError("未找到微软商店版 Codex")
    config = load_config()
    config["codex_path"] = codex_path
    save_config(config)
    return {"codexPath": codex_path, "codexVersion": get_file_version(codex_path)}


def refresh_profile_usage(payload):
    """刷新单个账号的额度快照。"""
    name = payload.get("name", "")
    config = load_config()
    if name not in config.get("profiles", []):
        raise ValueError("账号不存在")
    usage = refresh_profile_usage_cache(name, _get_profile_dir(config, name))
    return {"name": name, "usage": usage}


def refresh_all_profile_usage(_payload=None):
    """刷新全部账号的额度快照。"""
    config = load_config()
    profile_dirs = {
        profile_name: str(_get_profile_dir(config, profile_name))
        for profile_name in config.get("profiles", [])
    }
    return {"profiles": refresh_all_profile_usage_cache(profile_dirs)}


def set_profile_root(payload):
    """迁移整个账号根目录并保存新位置。"""
    new_root = Path(payload.get("profileRoot", ""))
    if not new_root:
        raise ValueError("账号根目录不能为空")
    if payload.get("asStorageLocation") and new_root.name.lower() != DEFAULT_PROFILE_ROOT.name.lower():
        new_root = new_root / DEFAULT_PROFILE_ROOT.name
    config = load_config()
    old_root = Path(config.get("profile_root") or DEFAULT_PROFILE_ROOT)
    old_root_resolved = old_root.resolve()
    new_root_parent = new_root.parent.resolve()
    new_root_resolved = new_root_parent / new_root.name

    if old_root_resolved == new_root_resolved:
        config["profile_root"] = str(new_root_resolved)
        save_config(config)
        return {"profileRoot": str(new_root_resolved), "migrated": False}
    if old_root_resolved in new_root_resolved.parents:
        raise ValueError("新位置不能放在当前账号目录内部")
    if new_root_resolved in old_root_resolved.parents:
        raise ValueError("新位置不能是当前账号目录的上级目录")

    new_root_parent.mkdir(parents=True, exist_ok=True)
    if not check_directory_writable(new_root_parent):
        raise PermissionError("账号根目录不可写")
    if new_root_resolved.exists() and any(new_root_resolved.iterdir()):
        raise FileExistsError("目标账号根目录已存在且不为空")

    if old_root_resolved.exists():
        _cleanup_profile_root_before_move(old_root_resolved)
        _copy_directory(old_root_resolved, new_root_resolved)
        shutil.rmtree(old_root_resolved, onerror=remove_readonly_path)
    else:
        new_root_resolved.mkdir(parents=True, exist_ok=True)

    config["profile_root"] = str(new_root_resolved)
    save_config(config)
    return {"profileRoot": str(new_root_resolved), "migrated": True}


def set_session_sync(payload):
    """保存会话同步开关。"""
    config = load_config()
    config["session_sync_enabled"] = bool(payload.get("enabled", False))
    config["session_sync_root"] = payload.get("sessionSyncRoot") or str(DEFAULT_SESSION_SYNC_ROOT)
    save_config(config)
    return {
        "sessionSyncEnabled": config["session_sync_enabled"],
        "sessionSyncRoot": config["session_sync_root"],
    }


def set_memory_sync(payload):
    """保存记忆同步开关。"""
    config = load_config()
    config["memory_sync_enabled"] = bool(payload.get("enabled", False))
    save_config(config)
    return {"memorySyncEnabled": config["memory_sync_enabled"]}


def open_session_sync_dir(_payload=None):
    """创建并打开同步共享目录。"""
    config = load_config()
    sync_root = Path(config.get("session_sync_root") or DEFAULT_SESSION_SYNC_ROOT)
    sync_root.mkdir(parents=True, exist_ok=True)
    os.startfile(str(sync_root))
    return {"sessionSyncRoot": str(sync_root)}


def open_path(payload):
    """打开白名单命令传入的本地路径。"""
    path = Path(payload.get("path", ""))
    if not path.exists():
        raise FileNotFoundError(path)
    os.startfile(str(path))
    return {"path": str(path)}


def get_diagnostics(_payload=None):
    """生成结构化诊断数据。"""
    config = load_config()
    profiles = config.get("profiles", [])
    profile_root = Path(config.get("profile_root") or DEFAULT_PROFILE_ROOT)
    session_sync_root = Path(config.get("session_sync_root") or DEFAULT_SESSION_SYNC_ROOT)
    codex_path = config.get("codex_path", "")
    running_commands = read_running_codex_commands()
    profile_items = []
    for profile_name in profiles:
        summary = _build_profile_summary(config, profile_name, running_commands)
        health = _get_profile_health(config, profile_name, running_commands)
        status_text, _ = format_health_status(health)
        disk_usage_bytes = _get_directory_size(_get_profile_dir(config, profile_name))
        summary.update(
            {
                "statusText": status_text,
                "errors": health["errors"],
                "warnings": health["warnings"],
                "memoryDatabase": str(_get_profile_dir(config, profile_name) / "CodexHome" / MEMORY_SYNC_DB_NAME),
                "diskUsageBytes": disk_usage_bytes,
                "diskUsageText": _format_bytes(disk_usage_bytes),
            }
        )
        profile_items.append(summary)
    return {
        "basic": {
            "configPath": str(CONFIG_PATH),
            "configExists": CONFIG_PATH.exists(),
            "lastGoodBackupExists": CONFIG_LAST_GOOD_PATH.exists(),
            "previousGoodBackupExists": CONFIG_PREVIOUS_GOOD_PATH.exists(),
            "profileRoot": str(profile_root),
            "profileRootWritable": check_directory_writable(profile_root),
            "codexPath": codex_path or "未设置",
            "codexExists": bool(codex_path and Path(codex_path).exists()),
            "codexVersion": get_file_version(codex_path) if codex_path and Path(codex_path).exists() else "未识别",
            "defaultEnvPath": str(DEFAULT_CODEX_ENV_PATH),
            "defaultEnvExists": DEFAULT_CODEX_ENV_PATH.exists(),
            "profileCount": len(profiles),
            "sessionSyncEnabled": bool(config.get("session_sync_enabled", False)),
            "sessionSyncRoot": str(session_sync_root),
            "memorySyncEnabled": bool(config.get("memory_sync_enabled", False)),
            "memorySyncDatabase": str(session_sync_root / MEMORY_SYNC_DB_NAME),
        },
        "profiles": profile_items,
    }


def _build_profile_summary(config, profile_name, running_commands):
    """构造账号列表项，不在桥接层执行启动或迁移副作用。"""
    profile_dir = _get_profile_dir(config, profile_name)
    target_codex_path = profile_dir / PORTABLE_APP_DIR_NAME / "Codex.exe"
    codex_home_dir = profile_dir / "CodexHome"
    return {
        "name": profile_name,
        "running": _is_profile_running(config, profile_name, running_commands),
        "profileDir": str(profile_dir),
        "profileDirExists": profile_dir.exists(),
        "codexHome": str(codex_home_dir),
        "codexHomeExists": codex_home_dir.exists(),
        "portableCodexPath": str(target_codex_path),
        "portableCodexExists": target_codex_path.exists(),
        "usage": get_cached_profile_usage(profile_name),
    }


def _get_profile_dir(config, profile_name):
    """按现有规则计算账号目录，保持历史配置兼容。"""
    profile_root = Path(config.get("profile_root") or DEFAULT_PROFILE_ROOT)
    return profile_root / sanitize_profile_name(profile_name)


def _get_directory_size(directory):
    """统计账号目录实际占用的文件字节数，跳过链接目录避免循环扫描。"""
    if not directory.exists():
        return 0
    total_size = 0
    for root, dirs, files in os.walk(directory):
        root_path = Path(root)
        kept_dirs = []
        for directory_name in dirs:
            source_child = root_path / directory_name
            if is_reparse_point(source_child):
                continue
            kept_dirs.append(directory_name)
        dirs[:] = kept_dirs
        for file_name in files:
            file_path = root_path / file_name
            if is_reparse_point(file_path):
                continue
            try:
                total_size += file_path.stat().st_size
            except OSError:
                continue
    return total_size


def _format_bytes(size):
    """把字节数转成界面可读的磁盘占用文本。"""
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(size)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(value)} {unit}"
            return f"{value:.2f} {unit}"
        value /= 1024


def _get_user_data_dir(config, profile_name):
    """计算 Codex 网页容器的独立用户数据目录。"""
    return _get_profile_dir(config, profile_name) / "AppData" / "Roaming" / "Codex" / "web" / "Codex"


def _is_profile_running(config, profile_name, running_commands):
    """用旧逻辑里的环境目录特征判断账号是否运行。"""
    return any(target in running_commands for target in _get_profile_running_match_targets(config, profile_name))


def _get_profile_running_match_targets(config, profile_name):
    """构造用于识别账号运行进程的命令行路径特征。"""
    profile_dir = _get_profile_dir(config, profile_name)
    user_data_dir = profile_dir / "AppData" / "Roaming" / "Codex" / "web" / "Codex"
    return [
        normalize_path_for_match(profile_dir),
        normalize_path_for_match(user_data_dir),
    ]


def _validate_profile_name(config, profile_name, exclude_name=None):
    """校验账号名称和对应目录是否可用。"""
    profile_name = str(profile_name or "").strip()
    if not profile_name:
        raise ValueError("账号名称不能为空")
    profiles = config.setdefault("profiles", [])
    if profile_name in profiles and profile_name != exclude_name:
        raise ValueError("已存在同名账号")
    profile_dir = _get_profile_dir(config, profile_name)
    for existing_name in profiles:
        if exclude_name is not None and existing_name == exclude_name:
            continue
        if _get_profile_dir(config, existing_name).resolve() == profile_dir.resolve():
            raise ValueError(f"该名称对应的数据目录已被“{existing_name}”使用")
    if exclude_name is None and profile_dir.exists():
        raise FileExistsError("该名称对应的数据目录已存在")
    return profile_name


def _require_codex_path(config):
    """读取可用 Codex 路径，缺失时自动识别一次。"""
    codex_path = config.get("codex_path", "")
    if codex_path and Path(codex_path).exists():
        return codex_path
    codex_path = find_windowsapps_codex_path() or find_running_codex_path()
    if not codex_path:
        raise FileNotFoundError("未找到微软商店版 Codex")
    config["codex_path"] = codex_path
    save_config(config)
    return codex_path


def _get_profile_health(config, profile_name, running_commands):
    """检查账号目录、程序副本、配置目录和版本状态。"""
    codex_path = config.get("codex_path", "")
    profile_dir = _get_profile_dir(config, profile_name)
    codex_home_dir = profile_dir / "CodexHome"
    target_app_dir = profile_dir / PORTABLE_APP_DIR_NAME
    target_codex_path = target_app_dir / "Codex.exe"
    errors = []
    warnings = []
    if not profile_dir.exists():
        errors.append("账号目录不存在")
    elif not check_directory_writable(profile_dir):
        errors.append("账号目录不可写")
    if DEFAULT_CODEX_ENV_PATH.exists() and not (codex_home_dir / ".env").exists():
        warnings.append(".env 尚未同步")
    if codex_path and Path(codex_path).exists() and target_codex_path.exists():
        try:
            if portable_app_needs_update(codex_path, target_app_dir):
                warnings.append("程序副本需同步新版")
        except Exception:
            warnings.append("程序副本版本状态无法读取")
    if not target_codex_path.exists():
        warnings.append("程序副本不存在")
    return {
        "running": _is_profile_running(config, profile_name, running_commands),
        "errors": errors,
        "warnings": warnings,
    }


def _cleanup_profile_root_before_move(profile_root):
    """迁移前清理可丢弃临时目录，降低跨盘复制失败概率。"""
    if not profile_root.exists():
        return
    for profile_dir in profile_root.iterdir():
        temp_dir = profile_dir / "CodexHome" / ".tmp"
        if temp_dir.exists():
            shutil.rmtree(temp_dir, onerror=remove_readonly_path)


def _copy_directory(source_dir, target_dir):
    """复制账号根目录，跳过 junction 等特殊目录。"""
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
            shutil.copy2(source_file, target_root / file_name)
        try:
            shutil.copystat(root_path, target_root)
        except OSError:
            pass

