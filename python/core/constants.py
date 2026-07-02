import os
from pathlib import Path


APP_NAME = "Codex 多账号切换器"
ICON_FILE_NAME = "app.ico"
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CodexMultiLauncher"
CONFIG_PATH = CONFIG_DIR / "config.json"
CONFIG_LAST_GOOD_PATH = CONFIG_DIR / "config.json.last-good.json"
CONFIG_PREVIOUS_GOOD_PATH = CONFIG_DIR / "config.json.prev-good.json"
USAGE_CACHE_PATH = CONFIG_DIR / "usage_cache.json"
DEFAULT_PROFILE_ROOT = Path.home() / "Documents" / "CodexProfiles"

