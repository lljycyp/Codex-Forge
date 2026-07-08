from core import db
from core.constants import DEFAULT_PROFILE_ROOT


def load_config():
    """读取启动器配置。"""
    return normalize_config(db.load_config(default_config()))


def default_config():
    """生成默认配置，首次进入不预置任何账号。"""
    return {
        "profile_root": str(DEFAULT_PROFILE_ROOT),
        "profiles": [],
        "active_profile": "",
        "share_system_config": True,
        "launch_mode": "switch",
    }


def normalize_config(config):
    """补齐旧版本配置缺失的字段。"""
    defaults = default_config()
    for key, value in defaults.items():
        config.setdefault(key, value)
    if config.get("launch_mode") not in ("switch", "multi"):
        config["launch_mode"] = "switch"
    return config


def save_config(config):
    """保存启动器配置到 SQLite。"""
    db.save_config(normalize_config(config))
