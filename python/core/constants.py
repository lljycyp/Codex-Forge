import os
import re
from pathlib import Path


APP_NAME = "Codex 多账号启动器"
ICON_FILE_NAME = "app.ico"
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CodexMultiLauncher"
CONFIG_PATH = CONFIG_DIR / "config.json"
CONFIG_LAST_GOOD_PATH = CONFIG_DIR / "config.json.last-good.json"
CONFIG_PREVIOUS_GOOD_PATH = CONFIG_DIR / "config.json.prev-good.json"
DEFAULT_SESSION_SYNC_ROOT = CONFIG_DIR / "SharedSessions"
DEFAULT_PROFILE_ROOT = Path.home() / "Documents" / "CodexProfiles"
DEFAULT_CODEX_ENV_PATH = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".codex" / ".env"
PORTABLE_APP_DIR_NAME = "CodexPortableApp"
SOURCE_VERSION_FILE_NAME = ".source_version.json"
MEMORY_SYNC_DB_NAME = "memories_1.sqlite"
MEMORY_SYNC_SIDECAR_NAMES = ("memories_1.sqlite-wal", "memories_1.sqlite-shm")
MEMORY_SYNC_TABLE_NAMES = ("jobs", "stage1_outputs")
SESSION_SYNC_DIR_NAMES = ("sessions", "attachments", "ambient-suggestions")
SESSION_SYNC_FILE_NAMES = ("session_index.jsonl",)
SESSION_SYNC_STATE_DB_NAME = "state_5.sqlite"
SESSION_SYNC_STATE_SIDECAR_NAMES = ("state_5.sqlite-wal", "state_5.sqlite-shm")
SESSION_SYNC_STATE_TABLE_NAMES = ("threads", "thread_dynamic_tools", "thread_spawn_edges")
PROJECT_CONFIG_SECTION_RE = re.compile(r"^\[projects\.(?P<quote>['\"])(?P<path>.+?)(?P=quote)\]\s*$")
TOML_SECTION_RE = re.compile(r"^\[.+\]\s*$")
LOGIN_SENSITIVE_FILE_NAMES = {
    "auth.json",
    "Cookies",
    "Cookies-journal",
    "Login Data",
    "Login Data-journal",
}
LOGIN_SENSITIVE_DIR_NAMES = {
    "Local Storage",
    "Session Storage",
    "IndexedDB",
    "Service Worker",
    "Network",
    "WebStorage",
}

