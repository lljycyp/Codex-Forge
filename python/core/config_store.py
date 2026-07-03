import json
import os
import shutil

from core.constants import (
    CONFIG_DIR,
    CONFIG_LAST_GOOD_PATH,
    CONFIG_PATH,
    CONFIG_PREVIOUS_GOOD_PATH,
    DEFAULT_PROFILE_ROOT,
)


def load_config():
    """读取启动器配置；主配置损坏时尝试从最近备份恢复。"""
    if not CONFIG_PATH.exists():
        return default_config()

    try:
        return normalize_config(read_config_file(CONFIG_PATH))
    except Exception:
        backup_corrupted_config()

    for backup_path in (CONFIG_LAST_GOOD_PATH, CONFIG_PREVIOUS_GOOD_PATH):
        try:
            config = normalize_config(read_config_file(backup_path))
        except Exception:
            continue
        write_config_file(CONFIG_PATH, config)
        return config

    return default_config()


def default_config():
    """生成默认配置，首次进入不预置任何账号。"""
    return {
        "profile_root": str(DEFAULT_PROFILE_ROOT),
        "profiles": [],
        "active_profile": "",
        "share_system_config": True,
    }


def normalize_config(config):
    """补齐旧版本配置缺失的字段。"""
    defaults = default_config()
    for key, value in defaults.items():
        config.setdefault(key, value)
    return config


def save_config(config):
    """保存启动器配置，并保留最近两次可用备份。"""
    write_config_file(CONFIG_PATH, config)
    update_config_backups(config)


def read_config_file(path):
    """读取并解析指定配置文件。"""
    return json.loads(path.read_text(encoding="utf-8"))


def write_config_file(path, config):
    """用临时文件替换目标文件，避免中途失败导致配置损坏。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(config, ensure_ascii=False, indent=2)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(serialized, encoding="utf-8")
    os.replace(temp_path, path)


def update_config_backups(config):
    """轮转配置备份，最多保留最近两份可恢复配置。"""
    if CONFIG_LAST_GOOD_PATH.exists():
        shutil.copy2(CONFIG_LAST_GOOD_PATH, CONFIG_PREVIOUS_GOOD_PATH)
    write_config_file(CONFIG_LAST_GOOD_PATH, config)


def backup_corrupted_config():
    """备份损坏的主配置，方便用户后续排查。"""
    if not CONFIG_PATH.exists():
        return
    corrupted_path = CONFIG_DIR / "config.json.corrupt"
    try:
        shutil.copy2(CONFIG_PATH, corrupted_path)
    except Exception:
        pass

