import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from core.codex_source import (
    find_running_codex_path,
    find_windowsapps_codex_path,
    prepare_portable_codex_path,
    read_running_codex_commands,
    read_running_codex_processes,
)
from core.config_store import load_config, save_config
from core.constants import CONFIG_LAST_GOOD_PATH, CONFIG_PATH, CONFIG_PREVIOUS_GOOD_PATH, DEFAULT_PROFILE_ROOT, PORTABLE_APP_DIR_NAME
from core.auth_service import auth_tokens, extract_auth
from core.logger import get_logger
from core.oauth_service import login_with_browser
from core.path_utils import check_directory_writable, format_health_status, is_reparse_point, normalize_path_for_match, remove_readonly_path, sanitize_profile_name
from core.profile_service import (
    apply_profile,
    get_active_auth_path,
    get_active_codex_dir,
    get_active_config_path,
    get_profile_status,
    import_auth_json_profile,
    import_active_profile,
    ensure_profile_config_path,
    prepare_profile_codex_home,
    resolve_profile_auth_path,
    sync_codex_home_to_profile,
)
from core.instruction_service import (
    delete_instruction_template as delete_instruction_template_service,
    disable_instruction_template as disable_instruction_template_service,
    enable_instruction_template as enable_instruction_template_service,
    list_instruction_templates as list_instruction_templates_service,
    save_instruction_template as save_instruction_template_service,
    sync_instruction_template as sync_instruction_template_service,
)
from core.toml_config_service import read_toml_config as read_toml_config_service, save_toml_config as save_toml_config_service
from core.usage_service import (
    get_cached_profile_usage,
    refresh_all_profile_usage as refresh_all_profile_usage_cache,
    refresh_profile_usage as refresh_profile_usage_cache,
    remove_cached_usage,
    rename_cached_usage,
)


logger = get_logger(__name__)
SYSTEM_PROFILE_NAME = "__system__"


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
        "create_oauth_profile": create_oauth_profile,
        "create_auth_file_profile": create_auth_file_profile,
        "delete_profile": delete_profile,
        "get_app_state": get_app_state,
        "get_diagnostics": get_diagnostics,
        "list_instruction_templates": list_instruction_templates,
        "save_instruction_template": save_instruction_template,
        "delete_instruction_template": delete_instruction_template,
        "enable_instruction_template": enable_instruction_template,
        "disable_instruction_template": disable_instruction_template,
        "launch_profile": launch_profile,
        "list_profiles": list_profiles,
        "refresh_all_profile_usage": refresh_all_profile_usage,
        "refresh_codex_source": refresh_codex_source,
        "refresh_profile_usage": refresh_profile_usage,
        "read_toml_config": read_toml_config,
        "rename_profile": rename_profile,
        "save_toml_config": save_toml_config,
        "set_share_system_config": set_share_system_config,
        "set_launch_mode": set_launch_mode,
        "set_profile_root": set_profile_root,
        "open_path": open_path,
        "stop_profile": stop_profile,
    }
    handler = commands.get(command)
    if not handler:
        logger.warning("未知命令 命令=%s", command)
        return fail(f"未知命令：{command}")
    try:
        logger.info("命令开始 命令=%s", command)
        result = handler(payload)
        logger.info("命令成功 命令=%s", command)
        return ok(result)
    except Exception as exc:
        logger.exception("命令失败 命令=%s 错误=%s", command, exc)
        return fail(exc)


def get_app_state(_payload=None):
    """读取首页需要的账号切换状态。"""
    config = load_config()
    _normalize_profile_configs(config)
    profiles = config.get("profiles", [])
    profile_root = Path(config.get("profile_root") or DEFAULT_PROFILE_ROOT)
    running_count = _running_count_for_mode(config)
    return {
        "codexCommandAvailable": _is_codex_command_available(),
        "activeAuthPath": str(get_active_auth_path()),
        "activeAuthExists": get_active_auth_path().exists(),
        "activeConfigPath": str(get_active_config_path()),
        "activeConfigExists": get_active_config_path().exists(),
        "activeProfile": config.get("active_profile", ""),
        "shareSystemConfig": True,
        "launchMode": _get_launch_mode(config),
        "profileRoot": str(profile_root),
        "profileRootExists": profile_root.exists(),
        "profileCount": len(profiles),
        "runningCount": running_count,
    }


def list_profiles(_payload=None):
    """读取账号列表和每个账号资料状态。"""
    config = load_config()
    _normalize_profile_configs(config)
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
    logger.info("账号创建开始 名称=%s 目录=%s", name, profile_dir)
    import_active_profile(profile_dir)
    profiles = config.setdefault("profiles", [])
    profiles.append(name)
    config["active_profile"] = name
    save_config(config)
    logger.info("账号创建成功 名称=%s 目录=%s", name, profile_dir)
    return _build_profile_summary(config, name, read_running_codex_commands())


def create_oauth_profile(payload):
    """通过浏览器授权新增账号，不覆盖当前默认 Codex 账号资料。"""
    config = load_config()
    name = _validate_profile_name(config, payload.get("name", ""))
    logger.info("浏览器授权账号创建开始 名称=%s", name)
    auth_json = login_with_browser()
    profile_dir = _get_profile_dir(config, name)
    import_auth_json_profile(profile_dir, auth_json)
    profiles = config.setdefault("profiles", [])
    profiles.append(name)
    save_config(config)
    logger.info("浏览器授权账号创建成功 名称=%s 目录=%s", name, profile_dir)
    return _build_profile_summary(config, name, read_running_codex_commands())


def create_auth_file_profile(payload):
    """通过本地 auth.json 文件新增账号，不覆盖当前默认 Codex 账号资料。"""
    config = load_config()
    name = _validate_profile_name(config, payload.get("name", ""))
    auth_path = Path(payload.get("authJsonPath", ""))
    logger.info("本地认证文件账号创建开始 名称=%s 认证文件=%s", name, auth_path)
    if not auth_path.is_file() or auth_path.name.lower() != "auth.json":
        raise ValueError("请选择有效的 auth.json 文件")
    try:
        auth_json = json.loads(auth_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError("auth.json 内容不是有效的 JSON") from exc
    if not isinstance(auth_json, dict) or not auth_tokens(auth_json):
        raise ValueError("auth.json 内容不是有效的 Codex 登录信息")
    profile_dir = _get_profile_dir(config, name)
    import_auth_json_profile(profile_dir, auth_json)
    profiles = config.setdefault("profiles", [])
    profiles.append(name)
    save_config(config)
    logger.info("本地认证文件账号创建成功 名称=%s 目录=%s", name, profile_dir)
    return _build_profile_summary(config, name, read_running_codex_commands())


def rename_profile(payload):
    """修改账号名称，并移动对应资料目录。"""
    old_name = payload.get("oldName", "")
    config = load_config()
    if old_name not in config.get("profiles", []):
        raise ValueError("账号不存在")
    new_name = _validate_profile_name(config, payload.get("newName", ""), exclude_name=old_name)
    logger.info("账号重命名开始 原名称=%s 新名称=%s", old_name, new_name)
    if _is_profile_running(config, old_name):
        raise RuntimeError("该账号正在运行，请先关闭后再改名")
    old_dir = _get_profile_dir(config, old_name)
    new_dir = _get_profile_dir(config, new_name)
    if old_dir.exists() and old_dir != new_dir:
        if new_dir.exists():
            raise FileExistsError("目标账号资料目录已存在，请换一个账号名称")
        _move_profile_dir(config, old_dir, new_dir)
    profiles = config.setdefault("profiles", [])
    profiles[profiles.index(old_name)] = new_name
    if config.get("active_profile") == old_name:
        config["active_profile"] = new_name
    rename_cached_usage(old_name, new_name)
    save_config(config)
    logger.info("账号重命名成功 原名称=%s 新名称=%s", old_name, new_name)
    return _build_profile_summary(config, new_name, read_running_codex_commands())


def delete_profile(payload):
    """删除账号配置和账号资料目录。"""
    name = payload.get("name", "")
    config = load_config()
    profiles = config.setdefault("profiles", [])
    if name not in profiles:
        raise ValueError("账号不存在")
    if _is_profile_running(config, name):
        raise RuntimeError("该账号可能正在使用中，请先关闭 Codex")
    profile_dir = _get_profile_dir(config, name)
    logger.info("账号删除开始 名称=%s 目录=%s", name, profile_dir)
    if profile_dir.exists():
        shutil.rmtree(profile_dir, onerror=remove_readonly_path)
    profiles.remove(name)
    if config.get("active_profile") == name:
        config["active_profile"] = ""
    remove_cached_usage(name)
    save_config(config)
    logger.info("账号删除成功 名称=%s", name)
    return {"name": name}


def launch_profile(payload):
    """切换到指定账号资料，并启动默认安装的 Codex。"""
    name = payload.get("name", "")
    stop_running_first = bool(payload.get("stopRunningFirst"))
    config = load_config()
    if name not in config.get("profiles", []):
        raise ValueError("账号不存在")
    if _get_launch_mode(config) == "multi":
        return _launch_profile_multi(config, name)

    logger.info("账号启动开始 名称=%s 是否先关闭运行中实例=%s", name, stop_running_first)
    if _running_codex_count() > 0:
        if not stop_running_first:
            raise RuntimeError("检测到 Codex 正在运行，请先关闭后再切换账号")
        _stop_running_codex_processes()
        time.sleep(0.5)

    profile_dir = _get_profile_dir(config, name)
    apply_profile(
        profile_dir,
        share_system_config=True,
    )
    config["active_profile"] = name
    save_config(config)
    _launch_default_codex()
    logger.info("账号启动成功 名称=%s 目录=%s", name, profile_dir)
    return {"name": name, "activeAuthPath": str(get_active_auth_path()), "activeConfigPath": str(get_active_config_path())}


def stop_profile(_payload):
    """关闭当前运行的 Codex 进程。"""
    config = load_config()
    if _get_launch_mode(config) == "multi":
        return _stop_profile_multi(config, _payload or {})
    return _stop_running_codex_processes()


def _launch_profile_multi(config, name):
    """按账号隔离环境启动 Codex 桌面端。"""
    profile_dir = _get_profile_dir(config, name)
    running_commands = read_running_codex_commands()
    if _is_profile_running(config, name, running_commands):
        logger.info("多开账号已在运行 名称=%s", name)
        return {"name": name, "alreadyRunning": True}

    codex_path = _resolve_codex_app_source_path(config)
    appdata_dir = profile_dir / "AppData" / "Roaming"
    localappdata_dir = profile_dir / "AppData" / "Local"
    codex_home_dir = profile_dir / "CodexHome"
    user_data_dir = _get_user_data_dir(config, name)
    for directory in (appdata_dir, localappdata_dir, codex_home_dir, user_data_dir):
        directory.mkdir(parents=True, exist_ok=True)

    prepare_profile_codex_home(profile_dir)
    portable_codex_path = prepare_portable_codex_path(codex_path, profile_dir)

    env = os.environ.copy()
    env["APPDATA"] = str(appdata_dir)
    env["LOCALAPPDATA"] = str(localappdata_dir)
    env["CODEX_HOME"] = str(codex_home_dir)
    env["CODEX_MULTI_PROFILE"] = name

    logger.info("多开账号启动开始 名称=%s 程序=%s CODEX_HOME=%s", name, portable_codex_path, codex_home_dir)
    subprocess.Popen(
        [portable_codex_path, f"--user-data-dir={user_data_dir}"],
        cwd=str(Path(portable_codex_path).parent),
        env=env,
        close_fds=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    config["active_profile"] = name
    save_config(config)
    logger.info("多开账号启动成功 名称=%s 目录=%s", name, profile_dir)
    return {"name": name, "activeAuthPath": str(codex_home_dir / "auth.json"), "activeConfigPath": str(codex_home_dir / "config.toml")}


def _stop_profile_multi(config, payload):
    """关闭指定账号对应的 Codex 进程。"""
    name = payload.get("name", "")
    if name not in config.get("profiles", []):
        raise ValueError("账号不存在")
    match_targets = _get_profile_running_match_targets(config, name)
    matched_pids = [
        process["pid"]
        for process in read_running_codex_processes()
        if any(target in normalize_path_for_match(process["command_line"]) for target in match_targets)
    ]
    logger.info("多开账号关闭开始 名称=%s 匹配进程=%s", name, len(matched_pids))
    for pid in matched_pids:
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    sync_codex_home_to_profile(_get_profile_dir(config, name))
    logger.info("多开账号关闭成功 名称=%s 已关闭=%s", name, len(matched_pids))
    return {"name": name, "stopped": len(matched_pids)}


def _stop_running_codex_processes():
    """关闭当前运行的 Codex 进程，并返回实际发起关闭的数量。"""
    processes = read_running_codex_processes()
    stopped = 0
    logger.info("关闭 Codex 进程开始 数量=%s", len(processes))
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
    logger.info("关闭 Codex 进程成功 已关闭=%s", stopped)
    return {"stopped": stopped}


def refresh_codex_source(_payload=None):
    """刷新可启动的 Codex 程序来源，兼容无命令行别名的安装方式。"""
    config = load_config()
    launch_spec = _resolve_codex_launch_spec(config)
    logger.info("刷新 Codex 来源成功 类型=%s 显示=%s", launch_spec["kind"], launch_spec["display"])
    return {
        "codexCommandAvailable": True,
        "codexLaunchPath": launch_spec["display"],
    }


def read_toml_config(payload=None):
    """按当前启动模式读取系统或账号级 config.toml。"""
    config = load_config()
    target = _resolve_config_target(config, payload or {})
    return read_toml_config_service({"path": str(target["path"])})


def save_toml_config(payload):
    """按当前启动模式保存系统、单账号或全部账号 config.toml。"""
    config = load_config()
    payload = payload or {}
    if _get_launch_mode(config) == "multi" and payload.get("scope") == "all":
        profile_names = config.get("profiles", [])
        if not profile_names:
            raise ValueError("暂无账号可同步")
        result = None
        for profile_name in profile_names:
            target = _resolve_config_target(config, {"profileName": profile_name})
            result = save_toml_config_service({"path": str(target["path"]), "content": payload.get("content", "")})
        return {**(result or {}), "syncedCount": len(profile_names)}
    target = _resolve_config_target(config, payload)
    return save_toml_config_service({"path": str(target["path"]), "content": payload.get("content", "")})


def list_instruction_templates(payload=None):
    """按当前启动模式读取模板启用状态。"""
    config = load_config()
    target = _resolve_config_target(config, payload or {})
    return list_instruction_templates_service(_instruction_payload(target))


def save_instruction_template(payload):
    """按当前启动模式保存模板；multi 下保存到账号目录。"""
    config = load_config()
    payload = payload or {}
    target = _resolve_config_target(config, payload)
    return save_instruction_template_service({**payload, **_instruction_payload(target)})


def delete_instruction_template(payload):
    """按当前启动模式删除模板；multi 下删除账号目录内模板。"""
    config = load_config()
    payload = payload or {}
    target = _resolve_config_target(config, payload)
    return delete_instruction_template_service({**payload, **_instruction_payload(target)})


def enable_instruction_template(payload):
    """按当前启动模式启用模板；scope=all/profile 只同步模板文件。"""
    config = load_config()
    payload = payload or {}
    if _get_launch_mode(config) == "multi" and payload.get("scope") == "profile":
        target_profile_name = str(payload.get("targetProfileName") or "").strip()
        if target_profile_name not in config.get("profiles", []):
            raise ValueError("请选择有效目标账号")
        source_target = _resolve_config_target(config, payload)
        target = _resolve_config_target(config, {"profileName": target_profile_name})
        sync_payload = {
            "id": payload.get("id"),
            "targetTemplateDir": str(target["template_dir"]),
        }
        if source_target.get("template_dir"):
            sync_payload["templateDir"] = str(source_target["template_dir"])
        return sync_instruction_template_service(sync_payload)
    if _get_launch_mode(config) == "multi" and payload.get("scope") == "all":
        profile_names = config.get("profiles", [])
        if not profile_names:
            raise ValueError("暂无账号可同步")
        result = None
        source_target = _resolve_config_target(config, payload)
        for profile_name in profile_names:
            target = _resolve_config_target(config, {"profileName": profile_name})
            sync_payload = {
                "id": payload.get("id"),
                "targetTemplateDir": str(target["template_dir"]),
            }
            if source_target.get("template_dir"):
                sync_payload["templateDir"] = str(source_target["template_dir"])
            result = sync_instruction_template_service(sync_payload)
        return {**(result or {}), "syncedCount": len(profile_names)}
    target = _resolve_config_target(config, payload)
    return enable_instruction_template_service({
        "id": payload.get("id"),
        **_instruction_payload(target),
    })


def disable_instruction_template(payload=None):
    """按当前启动模式禁用模板。"""
    config = load_config()
    payload = payload or {}
    if _get_launch_mode(config) == "multi" and payload.get("scope") == "all":
        profile_names = config.get("profiles", [])
        if not profile_names:
            raise ValueError("暂无账号可同步")
        result = None
        for profile_name in profile_names:
            target = _resolve_config_target(config, {"profileName": profile_name})
            result = disable_instruction_template_service(_instruction_payload(target))
        return {**(result or {}), "syncedCount": len(profile_names)}
    target = _resolve_config_target(config, payload)
    return disable_instruction_template_service(_instruction_payload(target))


def refresh_profile_usage(payload):
    """刷新单个账号的额度快照。"""
    name = payload.get("name", "")
    config = load_config()
    if name not in config.get("profiles", []):
        raise ValueError("账号不存在")
    use_codex_home = _get_launch_mode(config) == "multi"
    if not use_codex_home:
        _sync_active_auth_to_profile(config, name)
    usage = refresh_profile_usage_cache(
        name,
        _get_profile_dir(config, name),
        share_system_config=not use_codex_home,
        use_codex_home_auth=use_codex_home,
    )
    return {"name": name, "usage": usage}


def refresh_all_profile_usage(_payload=None):
    """刷新全部账号的额度快照。"""
    config = load_config()
    use_codex_home = _get_launch_mode(config) == "multi"
    if not use_codex_home:
        _sync_active_auth_to_profile(config, config.get("active_profile", ""))
    profile_dirs = {
        profile_name: str(_get_profile_dir(config, profile_name))
        for profile_name in config.get("profiles", [])
    }
    return {
        "profiles": refresh_all_profile_usage_cache(
            profile_dirs,
            share_system_config=not use_codex_home,
            use_codex_home_auth=use_codex_home,
        )
    }


def set_share_system_config(payload):
    """兼容旧前端命令；账号切换模式固定使用系统 config.toml。"""
    config = load_config()
    config["share_system_config"] = True
    save_config(config)
    return {"shareSystemConfig": True}


def set_launch_mode(payload):
    """保存 Codex 启动模式。"""
    mode = str(payload.get("mode") or "").strip()
    if mode not in ("switch", "multi"):
        raise ValueError("启动模式无效")
    config = load_config()
    if mode == "switch" and _running_multi_profile_names(config):
        raise RuntimeError("请先关闭所有多开隔离模式下运行的 Codex，再切回账号切换模式")
    config["launch_mode"] = mode
    save_config(config)
    logger.info("启动模式已切换 模式=%s", mode)
    return {"launchMode": mode}


def _sync_active_auth_to_profile(config, profile_name):
    """当前账号刷新额度前，把 Codex 刚续期的认证回写到账号目录。"""
    if not profile_name or profile_name != config.get("active_profile"):
        return
    profile_dir = _get_profile_dir(config, profile_name)
    profile_auth_path = resolve_profile_auth_path(profile_dir)
    active_auth_path = get_active_auth_path()
    if not active_auth_path.exists() or not profile_auth_path.exists():
        return
    try:
        active_auth = json.loads(active_auth_path.read_text(encoding="utf-8"))
        profile_auth = json.loads(profile_auth_path.read_text(encoding="utf-8"))
        if not _is_same_auth_account(active_auth, profile_auth):
            logger.warning("跳过当前账号认证同步 原因=账号身份不一致 名称=%s", profile_name)
            return
        import_active_profile(profile_dir)
        logger.info("当前账号认证已同步 名称=%s 来源=%s 目标=%s", profile_name, active_auth_path, profile_auth_path)
    except Exception as exc:
        logger.warning("当前账号认证同步失败 名称=%s 错误=%s", profile_name, exc)


def _is_same_auth_account(left_auth, right_auth):
    """确认两个 auth.json 属于同一登录用户，避免同一 Team 账号下串号。"""
    left = extract_auth(left_auth)
    right = extract_auth(right_auth)
    left_claims = left.get("claims") if isinstance(left.get("claims"), dict) else {}
    right_claims = right.get("claims") if isinstance(right.get("claims"), dict) else {}
    for key in ("sub", "email"):
        left_value = left_claims.get(key) or left.get(key)
        right_value = right_claims.get(key) or right.get(key)
        if left_value or right_value:
            return bool(left_value and right_value and left_value == right_value)
    return bool(left.get("accountId") and left.get("accountId") == right.get("accountId"))


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
        logger.info("账号根目录未变化 路径=%s", new_root_resolved)
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
        logger.info("账号根目录迁移开始 原路径=%s 新路径=%s", old_root_resolved, new_root_resolved)
        _copy_directory(old_root_resolved, new_root_resolved)
        shutil.rmtree(old_root_resolved, onerror=remove_readonly_path)
    else:
        new_root_resolved.mkdir(parents=True, exist_ok=True)

    config["profile_root"] = str(new_root_resolved)
    save_config(config)
    logger.info("账号根目录设置成功 原路径=%s 新路径=%s", old_root_resolved, new_root_resolved)
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
    _normalize_profile_configs(config)
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
            "shareSystemConfig": True,
            "profileCount": len(profiles),
        },
        "profiles": profile_items,
    }


def _build_profile_summary(config, profile_name, running_commands):
    """构造账号列表项，不执行启动或迁移副作用。"""
    profile_dir = _get_profile_dir(config, profile_name)
    status = get_profile_status(
        profile_dir,
    )
    active_profile = config.get("active_profile", "")
    running = _is_profile_running(config, profile_name, running_commands)
    target_app_dir = profile_dir / PORTABLE_APP_DIR_NAME
    return {
        "name": profile_name,
        "running": running,
        "active": profile_name == active_profile,
        "profileDir": str(profile_dir),
        "profileDirExists": profile_dir.exists(),
        "authPath": status["authPath"],
        "authExists": status["authExists"],
        "configPath": status["configPath"],
        "configExists": status["configExists"],
        "codexHome": str(profile_dir / "CodexHome"),
        "codexHomeExists": (profile_dir / "CodexHome").exists(),
        "portableCodexPath": str(target_app_dir / "Codex.exe"),
        "portableCodexExists": (target_app_dir / "Codex.exe").exists(),
        "portableCodexSizeBytes": _get_directory_size(target_app_dir),
        "portableCodexSizeText": _format_bytes(_get_directory_size(target_app_dir)),
        "usage": get_cached_profile_usage(profile_name),
    }


def _get_profile_dir(config, profile_name):
    """按现有规则计算账号资料目录，保持历史配置兼容。"""
    profile_root = Path(config.get("profile_root") or DEFAULT_PROFILE_ROOT)
    return profile_root / sanitize_profile_name(profile_name)


def _normalize_profile_configs(config):
    """开发期直接收敛账号配置：删除外层 config.toml，只保留 CodexHome/config.toml。"""
    for profile_name in config.get("profiles", []):
        ensure_profile_config_path(_get_profile_dir(config, profile_name))


def _resolve_config_target(config, payload):
    """switch 使用系统配置；multi 使用指定账号 CodexHome 配置。"""
    if _get_launch_mode(config) != "multi":
        return {"path": get_active_config_path(), "codex_home": get_active_codex_dir(), "template_dir": None, "profileName": ""}

    profile_name = str(payload.get("profileName") or config.get("active_profile") or "").strip()
    if profile_name == SYSTEM_PROFILE_NAME:
        return {"path": get_active_config_path(), "codex_home": get_active_codex_dir(), "template_dir": None, "profileName": SYSTEM_PROFILE_NAME}
    if not profile_name and config.get("profiles"):
        profile_name = config["profiles"][0]
    if profile_name not in config.get("profiles", []):
        raise ValueError("请选择有效账号")
    profile_dir = _get_profile_dir(config, profile_name)
    config_path = ensure_profile_config_path(profile_dir)
    return {
        "path": config_path,
        "codex_home": profile_dir / "CodexHome",
        "template_dir": profile_dir / "instruction_templates",
        "profileName": profile_name,
    }


def _instruction_payload(target):
    payload = {"codexHome": str(target["codex_home"]), "configPath": str(target["path"])}
    if target.get("template_dir"):
        payload["templateDir"] = str(target["template_dir"])
    return payload


def _move_profile_dir(config, old_dir, new_dir):
    """移动账号目录；目录被短暂占用时，改用复制后清理的方式完成改名。"""
    try:
        old_dir.rename(new_dir)
        return
    except PermissionError as exc:
        try:
            shutil.copytree(old_dir, new_dir, copy_function=shutil.copy2)
        except Exception as copy_exc:
            _remove_path_if_inside_profile_root(config, new_dir)
            raise RuntimeError("账号资料目录被占用，改名失败；请关闭相关窗口后重试") from copy_exc
        try:
            shutil.rmtree(old_dir, onerror=remove_readonly_path)
        except OSError:
            # 新目录已复制成功，旧目录若仍被系统占用则保留为孤立目录，避免改名结果回滚。
            pass
        return


def _remove_path_if_inside_profile_root(config, path):
    """仅清理账号根目录内的临时目标，防止异常路径被误删。"""
    profile_root = Path(config.get("profile_root") or DEFAULT_PROFILE_ROOT).resolve()
    target_path = Path(path).resolve()
    try:
        target_path.relative_to(profile_root)
    except ValueError:
        return
    if target_path.exists():
        shutil.rmtree(target_path, onerror=remove_readonly_path)


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
    status = get_profile_status(
        profile_dir,
    )
    return {
        "running": _is_profile_running(config, profile_name),
        "errors": status["errors"],
        "warnings": status["warnings"],
    }


def _get_launch_mode(config):
    """读取启动模式，异常值回退到稳定的账号切换模式。"""
    return "multi" if config.get("launch_mode") == "multi" else "switch"


def _is_profile_running(config, profile_name, running_commands=None):
    """判断指定账号是否为当前正在运行的账号。"""
    if _get_launch_mode(config) == "multi":
        running_commands = running_commands if running_commands is not None else read_running_codex_commands()
        return any(target in running_commands for target in _get_profile_running_match_targets(config, profile_name))
    return profile_name == config.get("active_profile", "") and _running_codex_count() > 0


def _running_count_for_mode(config):
    """按当前启动模式统计运行账号数。"""
    if _get_launch_mode(config) != "multi":
        return 1 if _running_codex_count() > 0 else 0
    running_commands = read_running_codex_commands()
    return sum(
        1
        for profile_name in config.get("profiles", [])
        if _is_profile_running(config, profile_name, running_commands)
    )


def _running_multi_profile_names(config):
    """列出当前仍在多开隔离环境中运行的账号。"""
    running_commands = read_running_codex_commands()
    return [
        profile_name
        for profile_name in config.get("profiles", [])
        if any(target in running_commands for target in _get_profile_running_match_targets(config, profile_name))
    ]


def _get_user_data_dir(config, profile_name):
    """计算 Codex 网页容器的独立用户数据目录。"""
    return _get_profile_dir(config, profile_name) / "AppData" / "Roaming" / "Codex" / "web" / "Codex"


def _get_profile_running_match_targets(config, profile_name):
    """构造用于识别账号运行进程的命令行路径特征。"""
    profile_dir = _get_profile_dir(config, profile_name)
    return [
        normalize_path_for_match(profile_dir),
        normalize_path_for_match(_get_user_data_dir(config, profile_name)),
    ]


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
        logger.info("Codex 启动来源已识别 来源=已配置桌面程序 路径=%s", configured_app_path)
        return _build_app_launch_spec(configured_app_path)

    detected_path = find_windowsapps_codex_path() or find_running_codex_path()
    if detected_path:
        config["codex_path"] = detected_path
        save_config(config)
        logger.info("Codex 启动来源已识别 来源=自动识别桌面程序 路径=%s", detected_path)
        return _build_app_launch_spec(detected_path)

    store_app_id = _find_windows_store_codex_app_id()
    if store_app_id:
        logger.info("Codex 启动来源已识别 来源=微软商店 应用标识=%s", store_app_id)
        return {
            "kind": "store",
            "command": ["explorer.exe", f"shell:AppsFolder\\{store_app_id}"],
            "display": store_app_id,
        }

    cli_path = _find_codex_cli_path(configured_path)
    if cli_path:
        logger.info("Codex 启动来源已识别 来源=命令行 路径=%s", cli_path)
        return {
            "kind": "cli",
            "command": [str(cli_path), "app"],
            "display": str(cli_path),
            "path_for_env": cli_path,
        }

    raise FileNotFoundError("未找到 Codex 程序，请在设置中重新识别或确认 Codex 已安装")


def _resolve_codex_app_source_path(config):
    """多开模式需要可复制的 Codex 桌面程序路径。"""
    configured_path = str(config.get("codex_path") or "").strip()
    configured_app_path = _resolve_configured_codex_app_path(configured_path)
    if configured_app_path:
        return configured_app_path

    detected_path = find_windowsapps_codex_path() or find_running_codex_path()
    if detected_path and Path(detected_path).exists():
        config["codex_path"] = detected_path
        save_config(config)
        return Path(detected_path)

    raise FileNotFoundError("多开隔离模式需要可识别的 Codex 桌面程序路径，请先刷新 Codex 来源或安装桌面版 Codex")


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
    logger.info("Codex 启动开始 类型=%s 显示=%s", launch_spec["kind"], launch_spec["display"])
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
        logger.info("Codex 启动成功 类型=%s 显示=%s", launch_spec["kind"], launch_spec["display"])
    except FileNotFoundError as exc:
        logger.exception("Codex 启动失败 显示=%s 错误=%s", launch_spec["display"], exc)
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
