import json
import os
import shutil
import time
import uuid
from pathlib import Path

from core.constants import DEFAULT_CODEX_ENV_PATH


def get_active_codex_dir():
    """返回默认 Codex 当前用户配置目录。"""
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".codex"


def get_active_auth_path():
    """返回当前生效的 Codex 认证文件路径。"""
    return get_active_codex_dir() / "auth.json"


def get_active_config_path():
    """返回当前生效的 Codex 配置文件路径。"""
    return get_active_codex_dir() / "config.toml"


def import_active_profile(profile_dir, share_system_config=False):
    """把当前生效的 Codex 账号资料保存为启动器账号资料。"""
    active_auth_path = get_active_auth_path()
    if not active_auth_path.exists():
        raise FileNotFoundError("当前 Codex 认证文件不存在，请先用默认 Codex 完成登录")

    profile_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(active_auth_path, profile_dir / "auth.json")
    ensure_profile_config_path(profile_dir)


def import_auth_json_profile(profile_dir, auth_json, share_system_config=False):
    """把指定授权内容保存为启动器账号资料，不改动当前默认 Codex。"""
    profile_dir.mkdir(parents=True, exist_ok=True)
    write_profile_auth_json(profile_dir / "auth.json", auth_json)
    ensure_profile_config_path(profile_dir)


def write_profile_auth_json(auth_path, auth_json):
    """原子写入账号 auth.json，避免刷新令牌时留下半截文件。"""
    auth_path = Path(auth_path)
    auth_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = auth_path.with_name(f".{auth_path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(
        json.dumps(auth_json, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp_path.replace(auth_path)


def ensure_profile_env_file(codex_home_dir):
    """确保账号 CodexHome 里有默认 .env；已有账号专属配置时不覆盖。"""
    target_env_path = Path(codex_home_dir) / ".env"
    if target_env_path.exists() or not DEFAULT_CODEX_ENV_PATH.exists():
        return
    target_env_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DEFAULT_CODEX_ENV_PATH, target_env_path)


def prepare_profile_codex_home(profile_dir, share_system_config=False):
    """把账号资料同步到多开模式使用的 CodexHome。"""
    migrate_legacy_profile_files(profile_dir)
    profile_dir = Path(profile_dir)
    source_auth_path = resolve_profile_auth_path(profile_dir)
    if not source_auth_path.exists():
        raise FileNotFoundError("账号认证文件不存在，无法启动")

    codex_home_dir = profile_dir / "CodexHome"
    codex_home_dir.mkdir(parents=True, exist_ok=True)
    ensure_profile_env_file(codex_home_dir)
    shutil.copy2(source_auth_path, codex_home_dir / "auth.json")
    ensure_profile_config_path(profile_dir)


def sync_codex_home_to_profile(profile_dir, share_system_config=False):
    """多开实例关闭后，把 CodexHome 中刷新过的认证回写到账号根目录。"""
    profile_dir = Path(profile_dir)
    codex_home_dir = profile_dir / "CodexHome"
    auth_path = codex_home_dir / "auth.json"
    if auth_path.exists():
        shutil.copy2(auth_path, profile_dir / "auth.json")


def migrate_legacy_profile_files(profile_dir):
    """把旧版外层 config.toml 收敛到 CodexHome/config.toml。"""
    profile_dir = Path(profile_dir)
    legacy_auth_path = profile_dir / "CodexHome" / "auth.json"
    root_auth_path = profile_dir / "auth.json"
    root_config_path = profile_dir / "config.toml"
    runtime_config_path = profile_dir / "CodexHome" / "config.toml"
    changed = False

    if legacy_auth_path.exists() and not root_auth_path.exists():
        shutil.copy2(legacy_auth_path, root_auth_path)
        changed = True
    if root_config_path.exists():
        runtime_config_path.parent.mkdir(parents=True, exist_ok=True)
        if not runtime_config_path.exists():
            shutil.copy2(root_config_path, runtime_config_path)
        root_config_path.unlink()
        changed = True
    return changed


def ensure_profile_config_path(profile_dir):
    """确保账号级配置只存在于 CodexHome/config.toml。"""
    profile_dir = Path(profile_dir)
    migrate_legacy_profile_files(profile_dir)
    config_path = resolve_profile_config_path(profile_dir)
    if config_path.exists():
        return config_path
    active_config_path = get_active_config_path()
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if active_config_path.exists():
        shutil.copy2(active_config_path, config_path)
    else:
        config_path.write_text("", encoding="utf-8")
    return config_path


def apply_profile(profile_dir, share_system_config=False):
    """把指定账号资料写入当前 Codex 活动配置。"""
    migrate_legacy_profile_files(profile_dir)
    source_auth_path = resolve_profile_auth_path(profile_dir)
    if not source_auth_path.exists():
        raise FileNotFoundError("账号认证文件不存在，无法切换")

    active_dir = get_active_codex_dir()
    active_dir.mkdir(parents=True, exist_ok=True)
    backup_active_files(active_dir)
    shutil.copy2(source_auth_path, get_active_auth_path())


def backup_active_files(active_dir):
    """切换前备份当前活动认证和配置，便于误操作恢复。"""
    backup_dir = active_dir / "account-switcher-backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    for file_name in ("auth.json", "config.toml"):
        source_path = active_dir / file_name
        if source_path.exists():
            shutil.copy2(source_path, backup_dir / f"{file_name}.{timestamp}.bak")


def get_profile_status(profile_dir, share_system_config=False):
    """检查账号资料是否完整。"""
    migrate_legacy_profile_files(profile_dir)
    auth_path = resolve_profile_auth_path(profile_dir)
    config_path = resolve_profile_config_path(profile_dir)
    errors = []
    warnings = []
    if not profile_dir.exists():
        errors.append("账号资料目录不存在")
    if not auth_path.exists():
        errors.append("账号认证文件不存在")
    if not config_path.exists():
        warnings.append("多开配置文件不存在，启动多开时会自动创建")
    return {
        "authPath": str(auth_path),
        "authExists": auth_path.exists(),
        "configPath": str(config_path),
        "configExists": config_path.exists(),
        "errors": errors,
        "warnings": warnings,
    }


def resolve_profile_auth_path(profile_dir):
    """兼容新版根目录认证文件和旧版 CodexHome 认证文件。"""
    profile_dir = Path(profile_dir)
    root_auth_path = profile_dir / "auth.json"
    if root_auth_path.exists():
        return root_auth_path
    return profile_dir / "CodexHome" / "auth.json"


def resolve_profile_config_path(profile_dir):
    """返回 multi 模式唯一账号级配置文件。"""
    profile_dir = Path(profile_dir)
    return profile_dir / "CodexHome" / "config.toml"
