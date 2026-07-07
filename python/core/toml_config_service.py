import shutil
import tomllib
from datetime import datetime
from pathlib import Path

from core.constants import CONFIG_DIR
from core.profile_service import get_active_config_path


BACKUP_DIR = CONFIG_DIR / "backups" / "config-toml"


def read_toml_config(_payload=None):
    """读取当前生效的 Codex config.toml 原文。"""
    path = get_active_config_path()
    return {
        "path": str(path),
        "exists": path.exists(),
        "content": path.read_text(encoding="utf-8") if path.exists() else "",
    }


def save_toml_config(payload):
    """校验并保存当前生效的 Codex config.toml，保存前备份旧文件。"""
    if "content" not in payload:
        raise ValueError("缺少 TOML 内容")
    content = str(payload.get("content") or "")
    try:
        tomllib.loads(content)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"TOML 语法错误：{exc}") from exc

    path = get_active_config_path()
    backup_path = _backup_config(path)
    _write_text_atomic(path, content.rstrip() + "\n")
    return {
        "path": str(path),
        "exists": True,
        "backupPath": str(backup_path) if backup_path else "",
        "content": path.read_text(encoding="utf-8"),
    }


def _backup_config(path):
    path = Path(path)
    if not path.exists():
        return None
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = BACKUP_DIR / f"config-{timestamp}.toml"
    shutil.copy2(path, backup_path)
    return backup_path


def _write_text_atomic(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(text, encoding="utf-8")
    temp_path.replace(path)
