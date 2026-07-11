import os
from pathlib import Path


APP_NAME = "ChatGPT Forge"
ICON_FILE_NAME = "app.ico"
_LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
CONFIG_DIR = _LOCAL_APPDATA / "ChatGPTForge"
DB_PATH = CONFIG_DIR / "chatgpt_forge.db"
LOG_DIR = CONFIG_DIR / "logs"
LOG_PATH = LOG_DIR / "launcher.log"
DEFAULT_PROFILE_ROOT = Path.home() / "Documents" / "CodexProfiles"
DEFAULT_CODEX_ENV_PATH = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".codex" / ".env"
PORTABLE_APP_DIR_NAME = "ChatGPTPortableApp"
SOURCE_VERSION_FILE_NAME = ".source_version.json"
