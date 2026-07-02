import os
import shutil
import subprocess
import time
from pathlib import Path

from core.codex_source import (
    find_running_codex_path,
    find_windowsapps_codex_path,
    read_running_codex_commands,
    read_running_codex_processes,
)
from core.config_store import load_config, save_config
from core.constants import CONFIG_LAST_GOOD_PATH, CONFIG_PATH, CONFIG_PREVIOUS_GOOD_PATH, DEFAULT_PROFILE_ROOT
from core.path_utils import check_directory_writable, format_health_status, is_reparse_point, normalize_path_for_match, remove_readonly_path, sanitize_profile_name
from core.profile_service import (
    apply_profile,
    get_active_auth_path,
    get_active_codex_dir,
    get_active_config_path,
    get_profile_status,
    import_active_profile,
)
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
        "refresh_all_profile_usage": refresh_all_profile_usage,
        "refresh_codex_source": refresh_codex_source,
        "refresh_profile_usage": refresh_profile_usage,
        "rename_profile": rename_profile,
        "set_profile_root": set_profile_root,
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
    """读取首页需要的账号切换状态。"""
    config = load_config()
    profiles = config.get("profiles", [])
    profile_root = Path(config.get("profile_root") or DEFAULT_PROFILE_ROOT)
    running_count = _running_codex_count()
    return {
        "codexCommandAvailable": _is_codex_command_available(),
        "activeAuthPath": str(get_active_auth_path()),
        "activeAuthExists": get_active_auth_path().exists(),
        "activeConfigPath": str(get_active_config_path()),
        "activeConfigExists": get_active_config_path().exists(),
        "activeProfile": config.get("active_profile", ""),
        "profileRoot": str(profile_root),
        "profileRootExists": profile_root.exists(),
        "profileCount": len(profiles),
        "runningCount": running_count,
    }


def list_profiles(_payload=None):
    """读取账号列表和每个账号资料状态。"""
    config = load_config()
    running_commands = read_running_codex_commands()
    return {
        "profiles": [
            _build_profile_summary(config, profile_name, running_commands)
            for profile_name in config.get("profiles", [])
        ]
    }


def create_profile(payload):
    """新增账号，把当前默认 Codex 账号资料保存到账号目录。"""
    config = load_config()
    name = _validate_profile_name(config, payload.get("name", ""))
    profile_dir = _get_profile_dir(config, name)
    import_active_profile(profile_dir)
    profiles = config.setdefault("profiles", [])
    profiles.append(name)
    config["active_profile"] = name
    save_config(config)
    return _build_profile_summary(config, name, read_running_codex_commands())


def rename_profile(payload):
    """修改账号名称，并移动对应资料目录。"""
    old_name = payload.get("oldName", "")
    config = load_config()
    if old_name not in config.get("profiles", []):
        raise ValueError("账号不存在")
    new_name = _validate_profile_name(config, payload.get("newName", ""), exclude_name=old_name)
    if _running_codex_count() > 0:
        raise RuntimeError("Codex 正在运行，请先关闭后再改名")
    old_dir = _get_profile_dir(config, old_name)
    new_dir = _get_profile_dir(config, new_name)
    if old_dir.exists() and old_dir != new_dir:
        if new_dir.exists():
            raise FileExistsError("目标账号资料目录已存在，请换一个账号名称")
        old_dir.rename(new_dir)
    profiles = config.setdefault("profiles", [])
    profiles[profiles.index(old_name)] = new_name
    if config.get("active_profile") == old_name:
        config["active_profile"] = new_name
    rename_cached_usage(old_name, new_name)
    save_config(config)
    return _build_profile_summary(config, new_name, read_running_codex_commands())


def delete_profile(payload):
    """删除账号配置和账号资料目录。"""
    name = payload.get("name", "")
    config = load_config()
    profiles = config.setdefault("profiles", [])
    if name not in profiles:
        raise ValueError("账号不存在")
    if config.get("active_profile") == name and _running_codex_count() > 0:
        raise RuntimeError("该账号可能正在使用中，请先关闭 Codex")
    profile_dir = _get_profile_dir(config, name)
    if profile_dir.exists():
        shutil.rmtree(profile_dir, onerror=remove_readonly_path)
    profiles.remove(name)
    if config.get("active_profile") == name:
        config["active_profile"] = ""
    remove_cached_usage(name)
    save_config(config)
    return {"name": name}


def launch_profile(payload):
    """切换到指定账号资料，并启动默认安装的 Codex。"""
    name = payload.get("name", "")
    stop_running_first = bool(payload.get("stopRunningFirst"))
    config = load_config()
    if name not in config.get("profiles", []):
        raise ValueError("账号不存在")
    if _running_codex_count() > 0:
        if not stop_running_first:
            raise RuntimeError("检测到 Codex 正在运行，请先关闭后再切换账号")
        _stop_running_codex_processes()
        time.sleep(0.5)

    profile_dir = _get_profile_dir(config, name)
    apply_profile(profile_dir)
    config["active_profile"] = name
    save_config(config)
    _launch_default_codex()
    return {"name": name, "activeAuthPath": str(get_active_auth_path()), "activeConfigPath": str(get_active_config_path())}


def stop_profile(_payload):
    """关闭当前运行的 Codex 进程。"""
    return _stop_running_codex_processes()


def _stop_running_codex_processes():
    """关闭当前运行的 Codex 进程，并返回实际发起关闭的数量。"""
    processes = read_running_codex_processes()
    stopped = 0
    for process in processes:
        pid = process.get("pid")
        if not pid:
            continue
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        stopped += 1
    return {"stopped": stopped}


def refresh_codex_source(_payload=None):
    """刷新可启动的 Codex 程序来源，兼容无命令行别名的安装方式。"""
    config = load_config()
    launch_spec = _resolve_codex_launch_spec(config)
    return {
        "codexCommandAvailable": True,
        "codexLaunchPath": launch_spec["display"],
    }


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
    """迁移整个账号资料根目录并保存新位置。"""
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
        _copy_directory(old_root_resolved, new_root_resolved)
        shutil.rmtree(old_root_resolved, onerror=remove_readonly_path)
    else:
        new_root_resolved.mkdir(parents=True, exist_ok=True)

    config["profile_root"] = str(new_root_resolved)
    save_config(config)
    return {"profileRoot": str(new_root_resolved), "migrated": True}


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
    running_commands = read_running_codex_commands()
    profile_items = []
    for profile_name in profiles:
        summary = _build_profile_summary(config, profile_name, running_commands)
        health = _get_profile_health(config, profile_name)
        status_text, _ = format_health_status(health)
        disk_usage_bytes = _get_directory_size(_get_profile_dir(config, profile_name))
        summary.update(
            {
                "statusText": status_text,
                "errors": health["errors"],
                "warnings": health["warnings"],
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
            "activeAuthPath": str(get_active_auth_path()),
            "activeAuthExists": get_active_auth_path().exists(),
            "activeConfigPath": str(get_active_config_path()),
            "activeConfigExists": get_active_config_path().exists(),
            "codexCommandAvailable": _is_codex_command_available(),
            "runningCodexCount": _running_codex_count(),
            "activeProfile": config.get("active_profile", ""),
            "profileCount": len(profiles),
        },
        "profiles": profile_items,
    }


def _build_profile_summary(config, profile_name, running_commands):
    """构造账号列表项，不执行启动或迁移副作用。"""
    profile_dir = _get_profile_dir(config, profile_name)
    status = get_profile_status(profile_dir)
    active_profile = config.get("active_profile", "")
    return {
        "name": profile_name,
        "running": profile_name == active_profile and bool(running_commands),
        "active": profile_name == active_profile,
        "profileDir": str(profile_dir),
        "profileDirExists": profile_dir.exists(),
        "authPath": status["authPath"],
        "authExists": status["authExists"],
        "configPath": status["configPath"],
        "configExists": status["configExists"],
        "usage": get_cached_profile_usage(profile_name),
    }


def _get_profile_dir(config, profile_name):
    """按现有规则计算账号资料目录，保持历史配置兼容。"""
    profile_root = Path(config.get("profile_root") or DEFAULT_PROFILE_ROOT)
    return profile_root / sanitize_profile_name(profile_name)


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
        raise FileExistsError("该名称对应的账号资料目录已存在")
    return profile_name


def _get_profile_health(config, profile_name):
    """检查账号资料完整性。"""
    profile_dir = _get_profile_dir(config, profile_name)
    status = get_profile_status(profile_dir)
    return {
        "running": profile_name == config.get("active_profile", "") and _running_codex_count() > 0,
        "errors": status["errors"],
        "warnings": status["warnings"],
    }


def _running_codex_count():
    """统计当前运行中的 Codex 相关进程数量。"""
    return len(read_running_codex_processes())


def _is_codex_command_available():
    """检查当前环境是否能找到可启动的 Codex 程序。"""
    try:
        _resolve_codex_launch_spec(load_config())
        return True
    except Exception:
        return False


def _resolve_codex_launch_spec(config):
    """参考 Codex Tools：优先桌面程序，其次商店应用标识，最后命令行。"""
    configured_path = str(config.get("codex_path") or "").strip()
    configured_app_path = _resolve_configured_codex_app_path(configured_path)
    if configured_app_path:
        return _build_app_launch_spec(configured_app_path)

    detected_path = find_windowsapps_codex_path() or find_running_codex_path()
    if detected_path:
        config["codex_path"] = detected_path
        save_config(config)
        return _build_app_launch_spec(detected_path)

    store_app_id = _find_windows_store_codex_app_id()
    if store_app_id:
        return {
            "kind": "store",
            "command": ["explorer.exe", f"shell:AppsFolder\\{store_app_id}"],
            "display": store_app_id,
        }

    cli_path = _find_codex_cli_path(configured_path)
    if cli_path:
        return {
            "kind": "cli",
            "command": [str(cli_path), "app"],
            "display": str(cli_path),
            "path_for_env": cli_path,
        }

    raise FileNotFoundError("未找到 Codex 程序，请在设置中重新识别或确认 Codex 已安装")


def _resolve_configured_codex_app_path(configured_path):
    """把用户保存的文件或目录解析为可启动的 Codex 桌面程序。"""
    if not configured_path:
        return None
    path = Path(configured_path)
    if path.is_file() and path.name.lower() in ("codex.exe", "codex desktop.exe"):
        return path
    if not path.is_dir():
        return None
    for candidate_dir in (path, path / "current", path / "app", path / "Application"):
        for file_name in ("Codex.exe", "Codex Desktop.exe"):
            candidate = candidate_dir / file_name
            if candidate.exists():
                return candidate
    return None


def _build_app_launch_spec(codex_path):
    """把桌面程序路径转换为启动说明，微软商店版改走应用标识。"""
    path = Path(codex_path)
    if _is_windows_store_codex_path(path):
        store_app_id = _find_windows_store_codex_app_id()
        if store_app_id:
            return {
                "kind": "store",
                "command": ["explorer.exe", f"shell:AppsFolder\\{store_app_id}"],
                "display": str(path),
            }
    return {
        "kind": "app",
        "command": [str(path)],
        "display": str(path),
        "cwd": str(path.parent),
    }


def _is_windows_store_codex_path(path):
    """判断路径是否指向微软商店版 Codex 安装目录。"""
    normalized = normalize_path_for_match(path)
    return "\\windowsapps\\openai.codex_" in normalized or "/windowsapps/openai.codex_" in normalized


def _find_windows_store_codex_app_id():
    """读取微软商店版 Codex 的应用启动标识。"""
    if os.name != "nt":
        return ""
    script = r"""
$ErrorActionPreference = 'SilentlyContinue'
$pattern = '^OpenAI\.Codex_[^!]+![^!]+$'
$matches = @()
$matches += Get-StartApps | Where-Object { $_.AppID -match $pattern } | Select-Object -ExpandProperty AppID
$pkg = Get-AppxPackage -Name 'OpenAI.Codex' | Select-Object -First 1
if ($null -ne $pkg) {
  $manifest = $pkg | Get-AppxPackageManifest
  foreach ($app in @($manifest.Package.Applications.Application)) {
    if ($null -ne $app -and $app.Id) {
      $matches += ('{0}!{1}' -f $pkg.PackageFamilyName, $app.Id)
    }
  }
}
$matches | Where-Object { $_ -match $pattern } | Sort-Object @{Expression = { $_ -notmatch '!App$' }}, @{Expression = { $_ }} | Select-Object -First 1
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    return next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")


def _find_codex_cli_path(configured_path=""):
    """查找 codex 命令行入口，补充桌面进程常见缺失的路径。"""
    candidates = []
    configured = Path(configured_path) if configured_path else None
    if configured and configured.is_file() and configured.name.lower() in ("codex", "codex.exe", "codex.cmd"):
        candidates.append(configured)
    if configured and configured.is_dir():
        for candidate_dir in (configured, configured / "bin", configured / "resources", configured / "resources" / "bin"):
            _append_codex_cli_candidates(candidates, candidate_dir)

    found = shutil.which("codex")
    if found:
        candidates.append(Path(found))

    for env_name in ("LOCALAPPDATA", "USERPROFILE"):
        base = os.environ.get(env_name)
        if not base:
            continue
        base_path = Path(base)
        search_dirs = [
            base_path / "Microsoft" / "WindowsApps",
            base_path / "AppData" / "Local" / "Microsoft" / "WindowsApps",
            base_path / "AppData" / "Local" / "Microsoft" / "WinGet" / "Links",
        ]
        for search_dir in search_dirs:
            _append_codex_cli_candidates(candidates, search_dir)

    seen = set()
    for candidate in candidates:
        normalized = normalize_path_for_match(candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _append_codex_cli_candidates(candidates, directory):
    """追加目录下可能存在的 codex 命令行文件。"""
    for file_name in ("codex.exe", "codex.cmd", "codex"):
        candidates.append(Path(directory) / file_name)


def _launch_default_codex():
    """启动默认安装的 Codex 桌面端。"""
    config = load_config()
    launch_spec = _resolve_codex_launch_spec(config)
    command = launch_spec["command"]
    env = os.environ.copy()
    path_for_env = launch_spec.get("path_for_env")
    if path_for_env:
        parent = str(Path(path_for_env).parent)
        env["PATH"] = parent + os.pathsep + env.get("PATH", "")
    try:
        subprocess.Popen(
            command,
            cwd=launch_spec.get("cwd"),
            env=env,
            close_fds=True,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError("未找到 Codex 程序，请在设置中重新识别或确认 Codex 已安装") from exc


def _get_directory_size(directory):
    """统计账号资料目录实际占用的文件字节数，跳过链接目录避免循环扫描。"""
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


def _copy_directory(source_dir, target_dir):
    """复制账号资料根目录，跳过 junction 等特殊目录。"""
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
