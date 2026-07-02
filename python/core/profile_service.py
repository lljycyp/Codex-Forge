import os
import shutil
import time
from pathlib import Path


def get_active_codex_dir():
    """返回默认 Codex 当前用户配置目录。"""
    return Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".codex"


def get_active_auth_path():
    """返回当前生效的 Codex 认证文件路径。"""
    return get_active_codex_dir() / "auth.json"


def get_active_config_path():
    """返回当前生效的 Codex 配置文件路径。"""
    return get_active_codex_dir() / "config.toml"


def import_active_profile(profile_dir):
    """把当前生效的 Codex 账号资料保存为启动器账号资料。"""
    active_auth_path = get_active_auth_path()
    active_config_path = get_active_config_path()
    if not active_auth_path.exists():
        raise FileNotFoundError("当前 Codex 认证文件不存在，请先用默认 Codex 完成登录")

    profile_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(active_auth_path, profile_dir / "auth.json")
    if active_config_path.exists():
        shutil.copy2(active_config_path, profile_dir / "config.toml")
    else:
        (profile_dir / "config.toml").write_text("", encoding="utf-8")


def migrate_legacy_profile_files(profile_dir):
    """把旧版 CodexHome 中的账号资料复制到新版账号根目录。"""
    profile_dir = Path(profile_dir)
    legacy_auth_path = profile_dir / "CodexHome" / "auth.json"
    legacy_config_path = profile_dir / "CodexHome" / "config.toml"
    root_auth_path = profile_dir / "auth.json"
    root_config_path = profile_dir / "config.toml"
    changed = False

    if legacy_auth_path.exists() and not root_auth_path.exists():
        shutil.copy2(legacy_auth_path, root_auth_path)
        changed = True
    if legacy_config_path.exists() and not root_config_path.exists():
        shutil.copy2(legacy_config_path, root_config_path)
        changed = True
    return changed


def apply_profile(profile_dir):
    """把指定账号资料写入当前 Codex 活动配置。"""
    migrate_legacy_profile_files(profile_dir)
    source_auth_path = resolve_profile_auth_path(profile_dir)
    source_config_path = resolve_profile_config_path(profile_dir)
    if not source_auth_path.exists():
        raise FileNotFoundError("账号认证文件不存在，无法切换")

    active_dir = get_active_codex_dir()
    active_dir.mkdir(parents=True, exist_ok=True)
    backup_active_files(active_dir)
    shutil.copy2(source_auth_path, get_active_auth_path())
    if source_config_path.exists():
        shutil.copy2(source_config_path, get_active_config_path())
    elif not get_active_config_path().exists():
        get_active_config_path().write_text("", encoding="utf-8")


def backup_active_files(active_dir):
    """切换前备份当前活动认证和配置，便于误操作恢复。"""
    backup_dir = active_dir / "account-switcher-backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    for file_name in ("auth.json", "config.toml"):
        source_path = active_dir / file_name
        if source_path.exists():
            shutil.copy2(source_path, backup_dir / f"{file_name}.{timestamp}.bak")


def get_profile_status(profile_dir):
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
        warnings.append("账号配置文件不存在，切换时会保留或创建空配置")
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
    """兼容新版根目录配置文件和旧版 CodexHome 配置文件。"""
    profile_dir = Path(profile_dir)
    root_config_path = profile_dir / "config.toml"
    if root_config_path.exists():
        return root_config_path
    return profile_dir / "CodexHome" / "config.toml"
