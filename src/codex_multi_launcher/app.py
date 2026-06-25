import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, simpledialog


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
        "codex_path": "",
        "profile_root": str(DEFAULT_PROFILE_ROOT),
        "profiles": [],
        "imported_original_profile": "",
        "session_sync_enabled": False,
        "session_sync_root": str(DEFAULT_SESSION_SYNC_ROOT),
        "memory_sync_enabled": False,
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


def resource_path(*parts):
    """获取源码运行或打包运行时都可访问的资源路径。"""
    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base_dir.joinpath(*parts)


def sanitize_profile_name(name):
    """把账号名称转换为可作为目录名的安全文本。"""
    cleaned = "".join(ch if ch not in r'<>:"/\|?*' else "_" for ch in name).strip()
    return cleaned or "账号"


def paths_equal(left, right):
    """宽松比较两个路径是否指向同一位置。"""
    try:
        return Path(left).resolve() == Path(right).resolve()
    except Exception:
        return normalize_path_for_match(left) == normalize_path_for_match(right)


def normalize_path_for_match(path):
    """把路径转换为便于在进程命令行中匹配的文本。"""
    return str(path).replace("/", "\\").rstrip("\\").lower()


def normalize_project_config_path(path):
    """归一化 config.toml 中的项目路径键。"""
    normalized = str(path).replace("/", "\\").rstrip("\\")
    if normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    return normalized.lower()


def normalize_cap_sid_project_path(path):
    """归一化 cap_sid 中的项目路径键。"""
    normalized = str(path).replace("\\", "/").rstrip("/")
    if normalized.startswith("//?/"):
        normalized = normalized[4:]
    return normalized.lower()


def read_running_codex_commands():
    """读取当前所有 Codex 相关进程的命令行。"""
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.Name -in @('Codex.exe','codex.exe') } | "
            "ForEach-Object { $_.CommandLine }"
        ),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return ""
    return normalize_path_for_match(result.stdout)


def find_windowsapps_codex_path():
    """自动查找微软商店版 Codex 主程序路径。"""
    package_path = find_windowsapps_codex_path_by_package()
    if package_path:
        return package_path
    return find_windowsapps_codex_path_by_scan()


def find_windowsapps_codex_path_by_package():
    """优先通过系统应用包信息查找微软商店版 Codex。"""
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-AppxPackage | "
            "Where-Object { "
            "$_.Name -like '*Codex*' -or "
            "$_.PackageFullName -like '*Codex*' -or "
            "$_.InstallLocation -like '*Codex*' "
            "} | "
            "Sort-Object Version -Descending | "
            "Select-Object -ExpandProperty InstallLocation"
        ),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return ""

    for line in result.stdout.splitlines():
        install_dir = Path(line.strip())
        codex_path = install_dir / "Codex.exe"
        if is_windowsapps_codex_path(codex_path):
            return str(codex_path)
    return ""


def find_windowsapps_codex_path_by_scan():
    """在 WindowsApps 目录里兜底扫描 Codex.exe。"""
    windows_apps_dir = get_windowsapps_dir()
    if not windows_apps_dir.exists():
        return ""

    candidates = []
    try:
        children = list(windows_apps_dir.iterdir())
    except Exception:
        return ""

    for child in children:
        if not child.is_dir():
            continue
        lowered_name = child.name.lower()
        if "codex" not in lowered_name and "openai" not in lowered_name:
            continue
        direct_codex_path = child / "Codex.exe"
        if direct_codex_path.exists():
            candidates.append(direct_codex_path)
            continue
        try:
            for root, _, files in os.walk(child):
                if "Codex.exe" in files:
                    candidates.append(Path(root) / "Codex.exe")
                    break
        except Exception:
            continue

    if not candidates:
        return ""
    candidates.sort(key=lambda path: get_source_signature(path).get("modified_ns", 0), reverse=True)
    return str(candidates[0])


def get_windowsapps_dir():
    """获取系统微软商店应用安装目录。"""
    program_files = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"
    return Path(program_files) / "WindowsApps"


def is_windowsapps_codex_path(path):
    """判断路径是否为微软商店应用目录里的 Codex.exe。"""
    path = Path(path)
    return path.exists() and path.name.lower() == "codex.exe" and "windowsapps" in normalize_path_for_match(path)


def find_running_codex_path():
    """从正在运行的 Codex 进程读取真实程序路径。"""
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        (
            "Get-Process -Name Codex -ErrorAction SilentlyContinue | "
            "Where-Object { $_.Path -and $_.Path -like '*Codex.exe' } | "
            "Select-Object -First 1 -ExpandProperty Path"
        ),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return ""
    path = result.stdout.strip()
    if path and Path(path).exists():
        return path
    return ""


def get_source_signature(codex_path):
    """读取源程序关键特征，用于判断账号副本是否需要更新。"""
    codex_path = Path(codex_path)
    try:
        stat = codex_path.stat()
    except OSError:
        return {}
    return {
        "source_path": str(codex_path),
        "source_dir": str(codex_path.parent),
        "file_version": get_file_version(codex_path),
        "size": stat.st_size,
        "modified_ns": stat.st_mtime_ns,
    }


def get_file_version(path):
    """读取可执行文件版本号；读取失败时返回空文本。"""
    escaped_path = str(path).replace("'", "''")
    command = [
        "powershell",
        "-NoProfile",
        "-Command",
        f"(Get-Item -LiteralPath '{escaped_path}').VersionInfo.FileVersion",
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return ""
    return result.stdout.strip()


def read_source_signature(target_app_dir):
    """读取账号程序副本记录的源程序版本信息。"""
    version_path = target_app_dir / SOURCE_VERSION_FILE_NAME
    if not version_path.exists():
        return {}
    try:
        return json.loads(version_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def write_source_signature(target_app_dir, signature):
    """写入账号程序副本对应的源程序版本信息。"""
    version_path = target_app_dir / SOURCE_VERSION_FILE_NAME
    version_path.write_text(json.dumps(signature, ensure_ascii=False, indent=2), encoding="utf-8")


def portable_app_needs_update(source_codex_path, target_app_dir):
    """判断账号程序副本是否缺失或落后于微软商店版。"""
    target_codex_path = target_app_dir / "Codex.exe"
    if not target_codex_path.exists():
        return True
    current_signature = get_source_signature(source_codex_path)
    saved_signature = read_source_signature(target_app_dir)
    if not saved_signature:
        return True
    return any(
        saved_signature.get(key) != current_signature.get(key)
        for key in ("source_path", "file_version", "size", "modified_ns")
    )


def prepare_portable_codex_path(source_codex_path, profile_dir, allow_update=True):
    """为账号准备独立 Codex 程序副本，并在源程序更新时同步。"""
    source_app_dir = Path(source_codex_path).parent
    target_app_dir = profile_dir / PORTABLE_APP_DIR_NAME
    target_codex_path = target_app_dir / "Codex.exe"
    if paths_equal(source_app_dir, target_app_dir):
        return str(Path(source_codex_path))
    if target_codex_path.exists() and not portable_app_needs_update(source_codex_path, target_app_dir):
        return str(target_codex_path)
    if target_codex_path.exists() and not allow_update:
        return str(target_codex_path)

    if target_app_dir.exists():
        shutil.rmtree(target_app_dir)
    profile_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_app_dir, target_app_dir, dirs_exist_ok=True)
    write_source_signature(target_app_dir, get_source_signature(source_codex_path))
    return str(target_codex_path)


def ensure_profile_env_file(codex_home_dir):
    """确保账号 CodexHome 里有默认 .env；已有账号专属配置时不覆盖。"""
    target_env_path = codex_home_dir / ".env"
    if target_env_path.exists() or not DEFAULT_CODEX_ENV_PATH.exists():
        return
    codex_home_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DEFAULT_CODEX_ENV_PATH, target_env_path)


def check_directory_writable(path):
    """检查目录是否可写，不保留测试文件。"""
    if not path.exists() or not path.is_dir():
        return False
    try:
        test_path = path / ".codex_multi_launcher_write_test"
        test_path.write_text("ok", encoding="utf-8")
        test_path.unlink()
        return True
    except Exception:
        return False


def format_health_status(health):
    """把账号健康检查结果转换成界面短状态。"""
    if health["running"]:
        return "运行中", "#16803c"
    if health["errors"]:
        return "异常", "#b42318"
    if health["warnings"]:
        return "需处理", "#9a5b00"
    return "就绪", "#666666"


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("760x500")
        self.resizable(False, False)
        self.set_window_icon()
        self.config_data = load_config()
        self.path_var = tk.StringVar(value=self.config_data.get("codex_path", ""))
        self.version_var = tk.StringVar(value="未识别")
        self.session_sync_var = tk.BooleanVar(value=bool(self.config_data.get("session_sync_enabled", False)))
        self.session_sync_root_var = tk.StringVar(value=self.config_data.get("session_sync_root", str(DEFAULT_SESSION_SYNC_ROOT)))
        self.memory_sync_var = tk.BooleanVar(value=bool(self.config_data.get("memory_sync_enabled", False)))
        detected_codex_path = find_windowsapps_codex_path()
        if detected_codex_path:
            self.config_data["codex_path"] = detected_codex_path
            self.path_var.set(detected_codex_path)
        self.migrate_original_profile_marker()
        self.build_ui()

    def set_window_icon(self):
        """设置窗口和任务栏图标；资源缺失时不影响主流程启动。"""
        icon_path = resource_path("assets", ICON_FILE_NAME)
        if not icon_path.exists():
            return
        try:
            self.iconbitmap(default=str(icon_path))
        except tk.TclError:
            return

    def migrate_original_profile_marker(self):
        """旧配置没有导入来源标记，默认把第一个已有账号视为已导入的原本账号。"""
        profiles = self.config_data.setdefault("profiles", [])
        imported_original_profile = self.config_data.get("imported_original_profile", "")
        if imported_original_profile in profiles:
            return
        if imported_original_profile:
            self.config_data["imported_original_profile"] = ""
            save_config(self.config_data)
            return
        if profiles:
            self.config_data["imported_original_profile"] = profiles[0]
            save_config(self.config_data)

    def build_ui(self):
        """构建主界面，提供自动识别、账号启动和账号新增。"""
        container = tk.Frame(self, padx=18, pady=16)
        container.pack(fill="both", expand=True)

        title = tk.Label(container, text="Codex 多账号启动器", font=("Microsoft YaHei UI", 15, "bold"))
        title.pack(anchor="w")

        tip = tk.Label(
            container,
            text="每个账号使用独立程序副本、数据目录和配置目录，登录信息互不复制。",
            font=("Microsoft YaHei UI", 9),
        )
        tip.pack(anchor="w", pady=(4, 14))

        path_row = tk.Frame(container)
        path_row.pack(fill="x")
        tk.Label(path_row, text="商店版地址：", font=("Microsoft YaHei UI", 9)).pack(side="left")
        path_entry = tk.Entry(path_row, textvariable=self.path_var)
        path_entry.configure(state="readonly", readonlybackground="white")
        path_entry.pack(side="left", fill="x", expand=True, padx=(6, 8))
        tk.Button(path_row, text="重新识别", command=self.choose_codex_path, width=10).pack(side="right")

        version_row = tk.Frame(container)
        version_row.pack(fill="x", pady=(8, 0))
        tk.Label(version_row, text="商店版版本：", font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Label(
            version_row,
            textvariable=self.version_var,
            anchor="w",
            font=("Microsoft YaHei UI", 9),
            fg="#444444",
        ).pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.refresh_store_info()

        sync_row = tk.Frame(container)
        sync_row.pack(fill="x", pady=(10, 0))
        tk.Checkbutton(
            sync_row,
            text="实验性同步会话",
            variable=self.session_sync_var,
            command=self.toggle_session_sync,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        sync_entry = tk.Entry(sync_row, textvariable=self.session_sync_root_var)
        sync_entry.configure(state="readonly", readonlybackground="white")
        sync_entry.pack(side="left", fill="x", expand=True, padx=(8, 8))
        tk.Button(sync_row, text="打开同步目录", command=self.open_session_sync_dir, width=14).pack(side="right")

        memory_row = tk.Frame(container)
        memory_row.pack(fill="x", pady=(6, 0))
        tk.Checkbutton(
            memory_row,
            text="实验性同步记忆",
            variable=self.memory_sync_var,
            command=self.toggle_memory_sync,
            font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        tk.Label(
            memory_row,
            text="启动账号前合并 memories_1.sqlite，不实时共享数据库。",
            anchor="w",
            font=("Microsoft YaHei UI", 9),
            fg="#666666",
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        profile_title = tk.Label(container, text="选择要启动的账号：", font=("Microsoft YaHei UI", 10, "bold"))
        profile_title.pack(anchor="w", pady=(18, 8))

        self.profile_frame = tk.Frame(container)
        self.profile_frame.pack(fill="both", expand=True)
        self.render_profiles()

        action_row = tk.Frame(container)
        action_row.pack(fill="x", pady=(12, 0))
        tk.Button(action_row, text="新增账号", command=self.add_profile, width=12).pack(side="left")
        tk.Button(action_row, text="导入原本账号", command=self.import_existing_profile, width=14).pack(
            side="left", padx=(8, 0)
        )
        tk.Button(action_row, text="刷新状态", command=self.render_profiles, width=12).pack(side="left", padx=(8, 0))
        tk.Button(action_row, text="诊断", command=self.show_diagnostics, width=10).pack(side="left", padx=(8, 0))
        tk.Button(action_row, text="打开配置目录", command=self.open_config_dir, width=14).pack(side="left", padx=(8, 0))

    def render_profiles(self):
        """刷新账号按钮列表。"""
        for child in self.profile_frame.winfo_children():
            child.destroy()
        profiles = self.config_data.get("profiles", [])
        self.ensure_all_profile_env_files()
        if not profiles:
            empty_tip = tk.Label(
                self.profile_frame,
                text="暂无账号，请点击左下角“新增账号”。",
                anchor="w",
                font=("Microsoft YaHei UI", 10),
            )
            empty_tip.pack(fill="x", pady=8)
            return
        running_commands = read_running_codex_commands()
        for index, name in enumerate(profiles, start=1):
            health = self.get_profile_health(name, running_commands)
            status_text, status_color = format_health_status(health)
            row = tk.Frame(self.profile_frame)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=f"{index}. {name}", anchor="w", font=("Microsoft YaHei UI", 10)).pack(
                side="left", fill="x", expand=True
            )
            tk.Label(row, text=status_text, fg=status_color, width=8, font=("Microsoft YaHei UI", 9)).pack(
                side="right", padx=(0, 8)
            )
            tk.Button(row, text="删除", command=lambda n=name: self.delete_profile(n), width=8).pack(side="right")
            tk.Button(row, text="改名", command=lambda n=name: self.rename_profile(n), width=8).pack(
                side="right", padx=(0, 8)
            )
            tk.Button(row, text="启动", command=lambda n=name: self.launch_profile(n), width=10).pack(
                side="right", padx=(0, 8)
            )

    def get_profile_dir(self, profile_name):
        """获取账号对应的独立数据目录。"""
        profile_root = Path(self.config_data.get("profile_root") or DEFAULT_PROFILE_ROOT)
        return profile_root / sanitize_profile_name(profile_name)

    def get_user_data_dir(self, profile_name):
        """获取 Codex Web 容器的独立用户数据目录。"""
        return self.get_profile_dir(profile_name) / "AppData" / "Roaming" / "Codex" / "web" / "Codex"

    def get_session_sync_root(self):
        """获取共享会话目录。"""
        configured_root = self.config_data.get("session_sync_root") or str(DEFAULT_SESSION_SYNC_ROOT)
        return Path(configured_root)

    def toggle_session_sync(self):
        """保存会话同步开关。"""
        enabled = bool(self.session_sync_var.get())
        self.config_data["session_sync_enabled"] = enabled
        self.config_data["session_sync_root"] = str(self.get_session_sync_root())
        save_config(self.config_data)
        if enabled:
            messagebox.showinfo(
                "已开启实验性同步",
                "后续启动的账号会共享会话列表和附件。\n登录信息、配置、记忆和插件仍保持隔离。",
                parent=self,
            )

    def toggle_memory_sync(self):
        """保存记忆同步开关。"""
        enabled = bool(self.memory_sync_var.get())
        self.config_data["memory_sync_enabled"] = enabled
        save_config(self.config_data)
        if enabled:
            messagebox.showinfo(
                "已开启实验性记忆同步",
                "后续启动账号前会合并 Codex 记忆数据库。\n该功能不会共享登录信息、插件或完整配置。",
                parent=self,
            )

    def open_session_sync_dir(self):
        """打开共享会话目录。"""
        sync_root = self.get_session_sync_root()
        sync_root.mkdir(parents=True, exist_ok=True)
        os.startfile(str(sync_root))

    def ensure_all_profile_env_files(self):
        """为所有已登记账号补齐默认 .env。"""
        for profile_name in self.config_data.get("profiles", []):
            ensure_profile_env_file(self.get_profile_dir(profile_name) / "CodexHome")

    def find_profile_directory_owner(self, profile_name, exclude_name=None):
        """查找是否已有其他账号使用同一个安全目录名。"""
        profile_dir = self.get_profile_dir(profile_name)
        for existing_name in self.config_data.get("profiles", []):
            if exclude_name is not None and existing_name == exclude_name:
                continue
            if paths_equal(self.get_profile_dir(existing_name), profile_dir):
                return existing_name
        return None

    def validate_new_profile_name(self, profile_name, exclude_name=None):
        """校验账号名称和对应目录是否可用。"""
        profile_name = profile_name.strip()
        if not profile_name:
            messagebox.showwarning("名称为空", "请输入账号名称。", parent=self)
            return ""

        profiles = self.config_data.setdefault("profiles", [])
        if profile_name in profiles and profile_name != exclude_name:
            messagebox.showwarning("名称重复", "已存在同名账号，请换一个名称。", parent=self)
            return ""

        owner = self.find_profile_directory_owner(profile_name, exclude_name=exclude_name)
        if owner:
            messagebox.showwarning(
                "目录冲突",
                f"该名称对应的数据目录已被“{owner}”使用，请换一个名称。",
                parent=self,
            )
            return ""

        profile_dir = self.get_profile_dir(profile_name)
        if exclude_name is None and profile_dir.exists():
            messagebox.showwarning(
                "目录已存在",
                "该名称对应的数据目录已存在，请换一个名称，或先手动确认该目录是否还需要保留。",
                parent=self,
            )
            return ""
        return profile_name

    def is_profile_running(self, profile_name, running_commands):
        """根据进程命令行判断账号是否正在运行。"""
        profile_dir = self.get_profile_dir(profile_name)
        user_data_dir = self.get_user_data_dir(profile_name)
        match_targets = [
            normalize_path_for_match(profile_dir),
            normalize_path_for_match(user_data_dir),
        ]
        return any(target in running_commands for target in match_targets)

    def get_profile_health(self, profile_name, running_commands=None):
        """检查账号目录、程序副本、配置目录和版本状态。"""
        running_commands = running_commands if running_commands is not None else read_running_codex_commands()
        codex_path = self.config_data.get("codex_path", "")
        profile_dir = self.get_profile_dir(profile_name)
        codex_home_dir = profile_dir / "CodexHome"
        appdata_dir = profile_dir / "AppData" / "Roaming"
        localappdata_dir = profile_dir / "AppData" / "Local"
        user_data_dir = self.get_user_data_dir(profile_name)
        target_app_dir = profile_dir / PORTABLE_APP_DIR_NAME
        target_codex_path = target_app_dir / "Codex.exe"
        errors = []
        warnings = []

        if not profile_dir.exists():
            errors.append("账号目录不存在")
        if not target_codex_path.exists():
            errors.append("程序副本缺失")
        if not codex_home_dir.exists():
            errors.append("CodexHome 目录缺失")
        if not appdata_dir.exists():
            warnings.append("APPDATA 目录尚未创建")
        if not localappdata_dir.exists():
            warnings.append("LOCALAPPDATA 目录尚未创建")
        if not user_data_dir.exists():
            warnings.append("Web 容器数据目录尚未创建")
        if not check_directory_writable(profile_dir):
            errors.append("账号目录不可写")
        if DEFAULT_CODEX_ENV_PATH.exists() and not (codex_home_dir / ".env").exists():
            warnings.append(".env 尚未同步")
        if codex_path and Path(codex_path).exists() and target_codex_path.exists():
            try:
                if portable_app_needs_update(codex_path, target_app_dir):
                    warnings.append("程序副本需同步新版")
            except Exception:
                warnings.append("程序副本版本状态无法读取")

        return {
            "running": self.is_profile_running(profile_name, running_commands),
            "errors": errors,
            "warnings": warnings,
        }

    def refresh_store_info(self, codex_path=None):
        """刷新界面展示的微软商店版地址和版本号。"""
        codex_path = codex_path or self.config_data.get("codex_path", "")
        self.path_var.set(codex_path)
        if not codex_path or not Path(codex_path).exists():
            self.version_var.set("未识别")
            return
        version = get_file_version(codex_path)
        self.version_var.set(version or "无法读取")

    def choose_codex_path(self):
        """重新自动识别微软商店版 Codex 主程序路径。"""
        selected = find_windowsapps_codex_path()
        if not selected:
            self.refresh_store_info()
            messagebox.showwarning(
                "未找到程序",
                "没有自动找到微软商店版 Codex。\n请确认已从微软商店安装，并以管理员身份运行启动器。",
                parent=self,
            )
            return ""
        self.config_data["codex_path"] = selected
        self.refresh_store_info(selected)
        save_config(self.config_data)
        return selected

    def get_store_codex_path(self):
        """获取最新微软商店版 Codex 主程序路径。"""
        latest_codex_path = find_windowsapps_codex_path()
        if latest_codex_path:
            self.config_data["codex_path"] = latest_codex_path
            self.refresh_store_info(latest_codex_path)
            save_config(self.config_data)
            return latest_codex_path

        codex_path = self.config_data.get("codex_path", "")
        if is_windowsapps_codex_path(codex_path):
            self.refresh_store_info(codex_path)
            return codex_path
        return self.choose_codex_path()

    def add_profile(self):
        """新增一个账号入口。"""
        name = simpledialog.askstring("新增账号", "请输入账号名称，例如：工作号、个人号：", parent=self)
        if not name:
            return
        name = self.validate_new_profile_name(name)
        if not name:
            return
        codex_path = self.get_store_codex_path()
        if not codex_path:
            return
        profile_dir = self.get_profile_dir(name)
        ensure_profile_env_file(profile_dir / "CodexHome")
        try:
            prepare_portable_codex_path(codex_path, profile_dir)
        except Exception as exc:
            try:
                if profile_dir.exists():
                    shutil.rmtree(profile_dir)
            except Exception:
                pass
            messagebox.showerror(
                "新增失败",
                f"无法复制微软商店版 Codex：\n{exc}\n\n请确认已以管理员身份运行启动器。",
                parent=self,
            )
            return
        profiles = self.config_data.setdefault("profiles", [])
        profiles.append(name)
        save_config(self.config_data)
        self.render_profiles()

    def rename_profile(self, old_name):
        """修改账号显示名称，并同步移动对应数据目录。"""
        new_name = simpledialog.askstring("修改账号名称", "请输入新的账号名称：", initialvalue=old_name, parent=self)
        if not new_name:
            return

        new_name = self.validate_new_profile_name(new_name, exclude_name=old_name)
        if not new_name or new_name == old_name:
            return

        profiles = self.config_data.setdefault("profiles", [])
        profile_root = Path(self.config_data.get("profile_root") or DEFAULT_PROFILE_ROOT)
        old_dir = self.get_profile_dir(old_name)
        new_dir = profile_root / sanitize_profile_name(new_name)

        if old_dir != new_dir and new_dir.exists():
            messagebox.showwarning("目录已存在", "新名称对应的数据目录已存在，请换一个名称。", parent=self)
            return

        if old_dir.exists() and old_dir != new_dir:
            try:
                old_dir.rename(new_dir)
            except Exception:
                messagebox.showerror(
                    "改名失败",
                    "账号数据目录可能正在被 Codex 占用。\n请关闭对应 Codex 后再修改名称。",
                    parent=self,
                )
                return

        self.config_data["profiles"] = [new_name if name == old_name else name for name in profiles]
        if self.config_data.get("imported_original_profile") == old_name:
            self.config_data["imported_original_profile"] = new_name
        save_config(self.config_data)
        self.render_profiles()
        messagebox.showinfo("已修改", f"已将“{old_name}”改为“{new_name}”。", parent=self)

    def import_existing_profile(self):
        """把当前默认 Codex 配置复制成独立账号，但不复制登录态。"""
        profiles = self.config_data.setdefault("profiles", [])
        imported_original_profile = self.config_data.get("imported_original_profile", "")
        if imported_original_profile in profiles:
            messagebox.showinfo(
                "已导入过",
                f"原本账号已导入为：{imported_original_profile}\n不需要重复导入。",
                parent=self,
            )
            return

        name = simpledialog.askstring("导入原本账号", "请输入导入后的账号名称：", initialvalue="原本账号", parent=self)
        if not name:
            return

        profile_name = self.validate_new_profile_name(name)
        if not profile_name:
            return
        profile_dir = self.get_profile_dir(profile_name)
        appdata_dir = profile_dir / "AppData" / "Roaming"
        codex_home_dir = profile_dir / "CodexHome"
        appdata_dir.mkdir(parents=True, exist_ok=True)
        codex_home_dir.mkdir(parents=True, exist_ok=True)

        copied_any = False
        source_roaming_codex = Path(os.environ.get("APPDATA", "")) / "Codex"
        target_roaming_codex = appdata_dir / "Codex"
        if source_roaming_codex.exists():
            self.copy_directory(source_roaming_codex, target_roaming_codex, skip_login_data=True)
            copied_any = True

        source_codex_home = Path.home() / ".codex"
        if source_codex_home.exists():
            self.copy_directory(source_codex_home, codex_home_dir, skip_login_data=True)
            copied_any = True
        ensure_profile_env_file(codex_home_dir)

        if not copied_any:
            try:
                if profile_dir.exists():
                    shutil.rmtree(profile_dir)
            except Exception:
                pass
            messagebox.showwarning("未找到原本账号", "没有找到可导入的 Codex 默认数据目录。")
            return

        codex_path = self.get_store_codex_path()
        if not codex_path:
            try:
                if profile_dir.exists():
                    shutil.rmtree(profile_dir)
            except Exception:
                pass
            return
        try:
            prepare_portable_codex_path(codex_path, profile_dir)
        except Exception as exc:
            try:
                if profile_dir.exists():
                    shutil.rmtree(profile_dir)
            except Exception:
                pass
            messagebox.showerror(
                "导入失败",
                f"无法复制微软商店版 Codex：\n{exc}\n\n请确认已以管理员身份运行启动器。",
                parent=self,
            )
            return

        if profile_name not in profiles:
            profiles.append(profile_name)
        self.config_data["imported_original_profile"] = profile_name
        save_config(self.config_data)
        self.render_profiles()
        messagebox.showinfo(
            "导入完成",
            f"已导入配置：{profile_name}\n登录信息没有复制，首次启动需要在该窗口单独登录。",
            parent=self,
        )

    def delete_profile(self, profile_name):
        """删除账号入口，并按用户确认清理对应隔离目录。"""
        running_commands = read_running_codex_commands()
        if self.is_profile_running(profile_name, running_commands):
            messagebox.showwarning(
                "账号正在运行",
                "请先关闭该账号对应的 Codex 窗口，再删除账号。",
                parent=self,
            )
            return

        confirmed = messagebox.askyesno(
            "确认删除",
            f"确定删除“{profile_name}”吗？\n\n这会移除启动器中的账号入口，并删除它的独立数据目录。",
            parent=self,
        )
        if not confirmed:
            return

        profile_dir = self.get_profile_dir(profile_name)
        if profile_dir.exists():
            try:
                shutil.rmtree(profile_dir)
            except Exception:
                messagebox.showwarning(
                    "删除失败",
                    "账号数据目录可能被占用，账号入口已保留。\n请关闭对应 Codex 后再删除。",
                    parent=self,
                )
                return

        profiles = self.config_data.setdefault("profiles", [])
        self.config_data["profiles"] = [name for name in profiles if name != profile_name]
        if self.config_data.get("imported_original_profile") == profile_name:
            self.config_data["imported_original_profile"] = ""

        save_config(self.config_data)
        self.render_profiles()
        messagebox.showinfo("已删除", f"已删除：{profile_name}", parent=self)

    def copy_directory(self, source, target, skip_login_data=False):
        """合并复制目录；可跳过登录相关文件，避免账号之间共享登录态。"""
        for root, dirs, files in os.walk(source):
            if skip_login_data:
                dirs[:] = [directory for directory in dirs if directory not in LOGIN_SENSITIVE_DIR_NAMES]
                files = [file_name for file_name in files if file_name not in LOGIN_SENSITIVE_FILE_NAMES]

            relative_root = Path(root).relative_to(source)
            target_root = target / relative_root
            target_root.mkdir(parents=True, exist_ok=True)
            for directory in dirs:
                (target_root / directory).mkdir(parents=True, exist_ok=True)
            for file_name in files:
                source_file = Path(root) / file_name
                target_file = target_root / file_name
                try:
                    shutil.copy2(source_file, target_file)
                except Exception:
                    # 少量缓存文件可能被占用，跳过不影响账号导入主流程。
                    continue

    def prepare_session_sync(self, codex_home_dir):
        """把账号 CodexHome 中的会话白名单路径挂到共享目录。"""
        if not self.config_data.get("session_sync_enabled", False):
            return

        sync_root = self.get_session_sync_root()
        sync_root.mkdir(parents=True, exist_ok=True)
        for directory_name in SESSION_SYNC_DIR_NAMES:
            self.prepare_shared_directory(codex_home_dir / directory_name, sync_root / directory_name)
        for file_name in SESSION_SYNC_FILE_NAMES:
            self.prepare_shared_file(codex_home_dir / file_name, sync_root / file_name)
        self.prepare_shared_state_database(codex_home_dir, sync_root)
        self.prepare_project_config_sync(codex_home_dir)
        self.prepare_project_cap_sid_sync(codex_home_dir)

    def prepare_memory_sync(self, codex_home_dir):
        """合并 Codex 记忆数据库，并写回本地真实文件。"""
        if not self.config_data.get("memory_sync_enabled", False):
            return

        sync_root = self.get_session_sync_root()
        sync_root.mkdir(parents=True, exist_ok=True)
        shared_path = sync_root / MEMORY_SYNC_DB_NAME

        if shared_path.exists() and not self.is_sqlite_database_healthy(shared_path):
            self.quarantine_sqlite_database_files(sync_root, MEMORY_SYNC_DB_NAME, MEMORY_SYNC_SIDECAR_NAMES, "corrupt-before-memory-sync")

        local_candidates = self.find_healthy_memory_databases(codex_home_dir)
        for local_candidate in local_candidates:
            if shared_path.exists():
                self.merge_sqlite_tables(local_candidate, shared_path, MEMORY_SYNC_TABLE_NAMES)
            else:
                self.copy_sqlite_database(local_candidate, shared_path)

        if shared_path.exists() and not self.is_sqlite_database_healthy(shared_path):
            self.quarantine_sqlite_database_files(sync_root, MEMORY_SYNC_DB_NAME, MEMORY_SYNC_SIDECAR_NAMES, "corrupt-before-memory-sync")

        if not shared_path.exists():
            return

        self.checkpoint_sqlite_database(shared_path)
        self.replace_local_sqlite_database(codex_home_dir, shared_path, MEMORY_SYNC_DB_NAME, MEMORY_SYNC_SIDECAR_NAMES)
        sqlite_dir = codex_home_dir / "sqlite"
        if sqlite_dir.exists():
            self.replace_local_sqlite_database(sqlite_dir, shared_path, MEMORY_SYNC_DB_NAME, MEMORY_SYNC_SIDECAR_NAMES)

    def find_healthy_memory_databases(self, codex_home_dir):
        """查找可用于合并的健康记忆数据库。"""
        candidates = [
            codex_home_dir / MEMORY_SYNC_DB_NAME,
            codex_home_dir / "sqlite" / MEMORY_SYNC_DB_NAME,
        ]
        candidates.extend(sorted(codex_home_dir.glob(f"{MEMORY_SYNC_DB_NAME}.local-before-memory-sync*")))
        healthy = []
        seen = set()
        for candidate in candidates:
            if candidate in seen or candidate.is_symlink():
                continue
            seen.add(candidate)
            if candidate.is_file() and self.is_sqlite_database_healthy(candidate):
                healthy.append(candidate)
        return healthy

    def prepare_shared_directory(self, local_path, shared_path):
        """合并已有本地目录后，用 junction 指向共享目录。"""
        shared_path.mkdir(parents=True, exist_ok=True)
        if self.is_linked_to_shared_path(local_path, shared_path):
            return

        if local_path.exists():
            if local_path.is_dir():
                self.copy_directory(local_path, shared_path)
            backup_path = self.next_sync_backup_path(local_path)
            local_path.rename(backup_path)

        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.create_directory_junction(local_path, shared_path)

    def prepare_shared_file(self, local_path, shared_path):
        """合并已有本地文件后，用符号链接指向共享文件。"""
        shared_path.parent.mkdir(parents=True, exist_ok=True)
        if local_path.exists() and local_path.is_file():
            if shared_path.exists():
                self.merge_text_lines(local_path, shared_path)
            else:
                shutil.copy2(local_path, shared_path)
        if not shared_path.exists():
            shared_path.write_text("", encoding="utf-8")
        if self.is_linked_to_shared_path(local_path, shared_path):
            return

        if local_path.exists():
            backup_path = self.next_sync_backup_path(local_path)
            local_path.rename(backup_path)

        local_path.parent.mkdir(parents=True, exist_ok=True)
        self.create_file_symlink(local_path, shared_path)

    def merge_text_lines(self, source_path, target_path):
        """把本地文本行合并进共享文件，保留已有顺序并去重。"""
        try:
            existing_lines = target_path.read_text(encoding="utf-8").splitlines()
            source_lines = source_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            return
        seen = set(existing_lines)
        merged_lines = list(existing_lines)
        for line in source_lines:
            if line in seen:
                continue
            merged_lines.append(line)
            seen.add(line)
        target_path.write_text("\n".join(merged_lines) + ("\n" if merged_lines else ""), encoding="utf-8")

    def prepare_project_config_sync(self, codex_home_dir):
        """把所有账号 config.toml 中的项目白名单合并到当前账号。"""
        target_config_path = codex_home_dir / "config.toml"
        project_sections = self.collect_project_config_sections()
        if not project_sections:
            return

        current_text = ""
        if target_config_path.exists():
            current_text = target_config_path.read_text(encoding="utf-8")

        existing_keys = self.extract_project_config_keys(current_text)
        missing_sections = [
            section_text
            for project_key, section_text in project_sections.items()
            if project_key not in existing_keys
        ]
        updated_text = current_text
        if missing_sections:
            separator = "\n\n" if current_text and not current_text.endswith("\n\n") else ""
            updated_text = current_text + separator + "\n\n".join(missing_sections) + "\n"
        updated_text = self.ensure_desktop_project_list_enabled(updated_text)

        if updated_text == current_text:
            return

        if target_config_path.exists():
            self.backup_file_once(target_config_path, "local-before-project-sync")
        target_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.write_text_atomic(target_config_path, updated_text)

    def ensure_desktop_project_list_enabled(self, text):
        """同步会话时打开项目侧栏依赖的桌面项目建议开关。"""
        lines = text.splitlines()
        desktop_index = self.find_toml_section_index(lines, "desktop")
        if desktop_index is None:
            return text.rstrip() + "\n\n[desktop]\nambient-suggestions-enabled = true\n"

        section_end = self.find_toml_section_end(lines, desktop_index + 1)
        for index in range(desktop_index + 1, section_end):
            if lines[index].strip().startswith("ambient-suggestions-enabled"):
                lines[index] = "ambient-suggestions-enabled = true"
                return "\n".join(lines).rstrip() + "\n"

        lines.insert(section_end, "ambient-suggestions-enabled = true")
        return "\n".join(lines).rstrip() + "\n"

    def find_toml_section_index(self, lines, section_name):
        """查找指定 TOML 顶层 section。"""
        section_header = f"[{section_name}]"
        for index, line in enumerate(lines):
            if line.strip() == section_header:
                return index
        return None

    def find_toml_section_end(self, lines, start_index):
        """查找 TOML section 结束位置。"""
        index = start_index
        while index < len(lines):
            if TOML_SECTION_RE.match(lines[index].strip()):
                return index
            index += 1
        return len(lines)

    def collect_project_config_sections(self):
        """从所有账号配置收集项目段。"""
        sections = {}
        for config_path in self.iter_profile_config_paths():
            if not config_path.exists():
                continue
            try:
                text = config_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for project_key, section_text in self.extract_project_config_sections(text).items():
                sections.setdefault(project_key, section_text)
        return sections

    def iter_profile_config_paths(self):
        """遍历所有账号的 config.toml。"""
        for profile_name in self.config_data.get("profiles", []):
            yield self.get_profile_dir(profile_name) / "CodexHome" / "config.toml"

    def extract_project_config_sections(self, text):
        """提取 TOML 中 [projects.'...'] 段。"""
        lines = text.splitlines()
        sections = {}
        index = 0
        while index < len(lines):
            header_match = PROJECT_CONFIG_SECTION_RE.match(lines[index].strip())
            if not header_match:
                index += 1
                continue

            start_index = index
            index += 1
            while index < len(lines) and not TOML_SECTION_RE.match(lines[index].strip()):
                index += 1

            project_key = normalize_project_config_path(header_match.group("path"))
            section_text = "\n".join(lines[start_index:index]).strip()
            if section_text:
                sections.setdefault(project_key, section_text)
        return sections

    def extract_project_config_keys(self, text):
        """提取 TOML 中已有项目路径键。"""
        return set(self.extract_project_config_sections(text).keys())

    def backup_file_once(self, path, suffix):
        """为文件创建一次性备份。"""
        backup_path = path.with_name(f"{path.name}.{suffix}")
        if backup_path.exists():
            return
        shutil.copy2(path, backup_path)

    def write_text_atomic(self, path, text):
        """原子写入文本文件。"""
        temp_path = path.with_name(f".{path.name}.tmp")
        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, path)

    def prepare_project_cap_sid_sync(self, codex_home_dir):
        """只合并 cap_sid 中的 workspace_by_cwd 项目注册表。"""
        merged_workspace_by_cwd = self.collect_workspace_by_cwd_entries()
        if not merged_workspace_by_cwd:
            return

        target_path = codex_home_dir / "cap_sid"
        target_data = self.read_cap_sid_file(target_path)
        if not target_data:
            target_data = {
                "workspace": "",
                "readonly": "",
                "workspace_by_cwd": {},
                "writable_root_by_path": {},
            }

        target_workspace_by_cwd = target_data.setdefault("workspace_by_cwd", {})
        changed = False
        for project_path, sid in merged_workspace_by_cwd.items():
            if project_path in target_workspace_by_cwd:
                continue
            target_workspace_by_cwd[project_path] = sid
            changed = True

        if not changed:
            return

        if target_path.exists():
            self.backup_file_once(target_path, "local-before-project-sync")
        self.write_json_atomic(target_path, target_data)

    def collect_workspace_by_cwd_entries(self):
        """从所有账号 cap_sid 收集 workspace_by_cwd。"""
        entries = {}
        for cap_sid_path in self.iter_profile_cap_sid_paths():
            data = self.read_cap_sid_file(cap_sid_path)
            workspace_by_cwd = data.get("workspace_by_cwd", {}) if data else {}
            if not isinstance(workspace_by_cwd, dict):
                continue
            for project_path, sid in workspace_by_cwd.items():
                if not isinstance(project_path, str) or not isinstance(sid, str):
                    continue
                entries.setdefault(normalize_cap_sid_project_path(project_path), sid)
        return entries

    def iter_profile_cap_sid_paths(self):
        """遍历所有账号的 cap_sid。"""
        for profile_name in self.config_data.get("profiles", []):
            yield self.get_profile_dir(profile_name) / "CodexHome" / "cap_sid"

    def read_cap_sid_file(self, path):
        """读取 cap_sid JSON；不存在或损坏时返回空字典。"""
        if not path.exists():
            return {}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def write_json_atomic(self, path, data):
        """原子写入 JSON 文件。"""
        temp_path = path.with_name(f".{path.name}.tmp")
        temp_path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        os.replace(temp_path, path)

    def prepare_shared_state_database(self, codex_home_dir, sync_root):
        """合并桌面端会话侧栏状态库，并写回本地真实文件。"""
        local_path = codex_home_dir / SESSION_SYNC_STATE_DB_NAME
        shared_path = sync_root / SESSION_SYNC_STATE_DB_NAME

        if shared_path.exists() and not self.is_sqlite_database_healthy(shared_path):
            self.quarantine_state_database_files(sync_root, "corrupt-before-sync")

        local_candidate = self.find_healthy_state_database(codex_home_dir)
        if local_candidate:
            if shared_path.exists():
                self.merge_state_database(local_candidate, shared_path)
            else:
                self.copy_sqlite_database(local_candidate, shared_path)
        elif local_path.exists() or local_path.is_symlink():
            self.quarantine_state_database_files(codex_home_dir, "corrupt-before-sync")

        if shared_path.exists() and not self.is_sqlite_database_healthy(shared_path):
            self.quarantine_state_database_files(sync_root, "corrupt-before-sync")

        if not shared_path.exists():
            self.remove_local_state_database_files(codex_home_dir)
            return

        self.checkpoint_sqlite_database(shared_path)
        self.replace_local_state_database(codex_home_dir, shared_path)

    def find_healthy_state_database(self, codex_home_dir):
        """查找可用于恢复共享状态库的健康本地状态库。"""
        candidates = [codex_home_dir / SESSION_SYNC_STATE_DB_NAME]
        candidates.extend(sorted(codex_home_dir.glob(f"{SESSION_SYNC_STATE_DB_NAME}.local-before-sync*")))
        candidates.extend(sorted(codex_home_dir.glob(f"{SESSION_SYNC_STATE_DB_NAME}.corrupt-before-sync*")))
        for candidate in candidates:
            if candidate.is_symlink():
                continue
            if candidate.is_file() and self.is_sqlite_database_healthy(candidate):
                return candidate
        return None

    def is_sqlite_database_healthy(self, database_path):
        """检查 SQLite 文件是否可读且完整。"""
        if not database_path.exists():
            return False
        try:
            connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
            try:
                result = connection.execute("PRAGMA integrity_check").fetchone()
                return result is not None and result[0] == "ok"
            finally:
                connection.close()
        except sqlite3.DatabaseError:
            return False
        except OSError:
            return False

    def quarantine_state_database_files(self, directory, suffix):
        """隔离损坏或旧版链接产生的状态库文件。"""
        self.quarantine_sqlite_database_files(
            directory,
            SESSION_SYNC_STATE_DB_NAME,
            SESSION_SYNC_STATE_SIDECAR_NAMES,
            suffix,
        )

    def quarantine_sqlite_database_files(self, directory, database_name, sidecar_names, suffix):
        """隔离损坏或旧版链接产生的 SQLite 文件。"""
        for file_name in (database_name, *sidecar_names):
            path = directory / file_name
            if not path.exists() and not path.is_symlink():
                continue
            quarantine_path = self.next_named_backup_path(path, suffix)
            path.rename(quarantine_path)

    def next_named_backup_path(self, path, suffix):
        """生成指定后缀的备份路径。"""
        candidate = path.with_name(f"{path.name}.{suffix}")
        index = 1
        while candidate.exists() or candidate.is_symlink():
            candidate = path.with_name(f"{path.name}.{suffix}.{index}")
            index += 1
        return candidate

    def merge_state_database(self, source_path, target_path):
        """把本地会话索引表合并进共享状态库。"""
        self.merge_sqlite_tables(source_path, target_path, SESSION_SYNC_STATE_TABLE_NAMES)

    def merge_sqlite_tables(self, source_path, target_path, table_names):
        """把指定 SQLite 表按主键忽略冲突地合并进目标库。"""
        source_connection = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        target_connection = sqlite3.connect(target_path)
        try:
            for table_name in table_names:
                self.merge_sqlite_table(source_connection, target_connection, table_name)
            target_connection.commit()
        finally:
            source_connection.close()
            target_connection.close()

    def checkpoint_sqlite_database(self, database_path):
        """尽量把 WAL 内容刷回主库，便于复制成独立本地库。"""
        connection = sqlite3.connect(database_path)
        try:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        finally:
            connection.close()

    def copy_sqlite_database(self, source_path, target_path):
        """使用 SQLite backup API 复制一致快照，避免遗漏 WAL 内容。"""
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target_path.with_name(f".{target_path.name}.sync-tmp")
        if temp_path.exists():
            temp_path.unlink()
        source_connection = sqlite3.connect(f"file:{source_path}?mode=ro", uri=True)
        target_connection = sqlite3.connect(temp_path)
        try:
            source_connection.backup(target_connection)
            target_connection.commit()
        finally:
            source_connection.close()
            target_connection.close()
        os.replace(temp_path, target_path)

    def merge_sqlite_table(self, source_connection, target_connection, table_name):
        """按主键忽略冲突地合并一个 SQLite 表。"""
        if not self.sqlite_table_exists(source_connection, table_name):
            return
        if not self.sqlite_table_exists(target_connection, table_name):
            return
        column_names = [
            row[1]
            for row in source_connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        ]
        if not column_names:
            return
        quoted_columns = ", ".join(f'"{column_name}"' for column_name in column_names)
        placeholders = ", ".join("?" for _ in column_names)
        select_sql = f"SELECT {quoted_columns} FROM {table_name}"
        insert_sql = f"INSERT OR IGNORE INTO {table_name} ({quoted_columns}) VALUES ({placeholders})"
        rows = source_connection.execute(select_sql).fetchall()
        target_connection.executemany(insert_sql, rows)

    def sqlite_table_exists(self, connection, table_name):
        """检查 SQLite 表是否存在。"""
        row = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
        return row is not None

    def backup_state_database_files(self, codex_home_dir):
        """备份本地状态库和 SQLite sidecar 文件。"""
        for file_name in (SESSION_SYNC_STATE_DB_NAME, *SESSION_SYNC_STATE_SIDECAR_NAMES):
            path = codex_home_dir / file_name
            if not path.exists() or path.is_symlink():
                continue
            backup_path = self.next_sync_backup_path(path)
            path.rename(backup_path)

    def replace_local_state_database(self, codex_home_dir, shared_path):
        """用共享索引生成本地真实 SQLite 文件，避免运行时跨进程共享 SQLite。"""
        self.replace_local_sqlite_database(
            codex_home_dir,
            shared_path,
            SESSION_SYNC_STATE_DB_NAME,
            SESSION_SYNC_STATE_SIDECAR_NAMES,
        )

    def replace_local_sqlite_database(self, directory, shared_path, database_name, sidecar_names):
        """用共享库生成本地真实 SQLite 文件，避免运行时跨进程共享 SQLite。"""
        directory.mkdir(parents=True, exist_ok=True)
        local_path = directory / database_name
        temp_path = local_path.with_name(f".{local_path.name}.sync-tmp")
        self.remove_local_sqlite_database_files(directory, database_name, sidecar_names)
        shutil.copy2(shared_path, temp_path)
        os.replace(temp_path, local_path)

    def remove_local_state_database_files(self, codex_home_dir):
        """清理旧的状态库链接和 WAL/SHM sidecar。"""
        self.remove_local_sqlite_database_files(
            codex_home_dir,
            SESSION_SYNC_STATE_DB_NAME,
            SESSION_SYNC_STATE_SIDECAR_NAMES,
        )

    def remove_local_sqlite_database_files(self, directory, database_name, sidecar_names):
        """清理旧的 SQLite 库链接和 WAL/SHM sidecar。"""
        for file_name in (database_name, *sidecar_names):
            path = directory / file_name
            if not path.exists() and not path.is_symlink():
                continue
            path.unlink()

    def remove_state_sidecar_links(self, codex_home_dir):
        """清理旧版创建的 SQLite WAL/SHM sidecar 链接。"""
        for file_name in SESSION_SYNC_STATE_SIDECAR_NAMES:
            local_path = codex_home_dir / file_name
            if local_path.is_symlink():
                local_path.unlink()

    def is_linked_to_shared_path(self, local_path, shared_path):
        """判断本地路径是否已经指向共享路径。"""
        if not local_path.exists() and not local_path.is_symlink():
            return False
        try:
            return paths_equal(local_path.resolve(), shared_path)
        except OSError:
            return False

    def next_sync_backup_path(self, path):
        """生成不会覆盖已有数据的同步前备份路径。"""
        base_name = f"{path.name}.local-before-sync"
        candidate = path.with_name(base_name)
        index = 1
        while candidate.exists():
            candidate = path.with_name(f"{base_name}.{index}")
            index += 1
        return candidate

    def create_directory_junction(self, link_path, target_path):
        """创建目录 junction，失败时抛出更清楚的错误。"""
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link_path), str(target_path)],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "无法创建目录 junction")

    def create_file_symlink(self, link_path, target_path):
        """创建文件符号链接，失败时抛出更清楚的错误。"""
        result = subprocess.run(
            ["cmd", "/c", "mklink", str(link_path), str(target_path)],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "无法创建文件符号链接")

    def open_config_dir(self):
        """打开启动器配置目录，方便用户查看生成的配置文件。"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(CONFIG_DIR))

    def show_diagnostics(self):
        """打开诊断窗口，展示当前环境和账号目录状态。"""
        report = self.build_diagnostic_report()
        window = tk.Toplevel(self)
        window.title("诊断报告")
        window.geometry("760x520")
        window.transient(self)

        text = tk.Text(window, wrap="word", font=("Microsoft YaHei UI", 9))
        text.pack(side="left", fill="both", expand=True)
        scrollbar = tk.Scrollbar(window, command=text.yview)
        scrollbar.pack(side="right", fill="y")
        text.configure(yscrollcommand=scrollbar.set)
        text.insert("1.0", report)
        text.configure(state="disabled")

    def build_diagnostic_report(self):
        """生成轻量诊断报告，帮助定位启动和隔离目录问题。"""
        lines = []
        profiles = self.config_data.get("profiles", [])
        profile_root = Path(self.config_data.get("profile_root") or DEFAULT_PROFILE_ROOT)
        codex_path = self.config_data.get("codex_path", "")
        running_commands = read_running_codex_commands()

        lines.append("Codex 多账号启动器诊断报告")
        lines.append("")
        lines.append("基础信息")
        lines.append(f"- 配置文件：{CONFIG_PATH}")
        lines.append(f"- 配置文件存在：{'是' if CONFIG_PATH.exists() else '否'}")
        lines.append(f"- 最近备份存在：{'是' if CONFIG_LAST_GOOD_PATH.exists() else '否'}")
        lines.append(f"- 上一次备份存在：{'是' if CONFIG_PREVIOUS_GOOD_PATH.exists() else '否'}")
        lines.append(f"- 账号根目录：{profile_root}")
        lines.append(f"- 账号根目录可写：{'是' if check_directory_writable(profile_root) else '否'}")
        lines.append(f"- 商店版路径：{codex_path or '未设置'}")
        lines.append(f"- 商店版存在：{'是' if codex_path and Path(codex_path).exists() else '否'}")
        lines.append(f"- 商店版版本：{get_file_version(codex_path) if codex_path and Path(codex_path).exists() else '未识别'}")
        lines.append(f"- 默认 .env：{DEFAULT_CODEX_ENV_PATH}")
        lines.append(f"- 默认 .env 存在：{'是' if DEFAULT_CODEX_ENV_PATH.exists() else '否'}")
        lines.append(f"- 已登记账号数：{len(profiles)}")
        lines.append(f"- 实验性会话同步：{'已开启' if self.config_data.get('session_sync_enabled', False) else '未开启'}")
        lines.append(f"- 实验性记忆同步：{'已开启' if self.config_data.get('memory_sync_enabled', False) else '未开启'}")
        lines.append(f"- 会话同步目录：{self.get_session_sync_root()}")
        lines.append(f"- 会话同步目录存在：{'是' if self.get_session_sync_root().exists() else '否'}")

        lines.append("")
        lines.append("账号状态")
        if not profiles:
            lines.append("- 暂无账号")
        for profile_name in profiles:
            profile_dir = self.get_profile_dir(profile_name)
            target_app_dir = profile_dir / PORTABLE_APP_DIR_NAME
            target_codex_path = target_app_dir / "Codex.exe"
            codex_home_dir = profile_dir / "CodexHome"
            health = self.get_profile_health(profile_name, running_commands)
            status_text, _ = format_health_status(health)
            lines.append(f"- {profile_name}")
            lines.append(f"  状态：{status_text}")
            lines.append(f"  账号目录：{profile_dir}")
            lines.append(f"  程序副本：{target_codex_path}")
            lines.append(f"  程序副本存在：{'是' if target_codex_path.exists() else '否'}")
            lines.append(f"  CodexHome：{codex_home_dir}")
            lines.append(f"  CodexHome 存在：{'是' if codex_home_dir.exists() else '否'}")
            lines.append(f"  项目注册数：{self.count_registered_project_workspaces(codex_home_dir)}")
            lines.append(f"  记忆数：{self.count_memory_records(codex_home_dir)}")
            if health["errors"]:
                lines.append(f"  异常：{'；'.join(health['errors'])}")
            if health["warnings"]:
                lines.append(f"  提醒：{'；'.join(health['warnings'])}")
            if not health["errors"] and not health["warnings"]:
                lines.append("  检查结果：未发现明显问题")

        return "\n".join(lines)

    def count_registered_project_workspaces(self, codex_home_dir):
        """统计 cap_sid 中已注册的项目工作区数量。"""
        data = self.read_cap_sid_file(codex_home_dir / "cap_sid")
        workspace_by_cwd = data.get("workspace_by_cwd", {}) if data else {}
        return len(workspace_by_cwd) if isinstance(workspace_by_cwd, dict) else 0

    def count_memory_records(self, codex_home_dir):
        """统计记忆数据库中的阶段输出数量。"""
        database_path = codex_home_dir / MEMORY_SYNC_DB_NAME
        if not database_path.exists() or not self.is_sqlite_database_healthy(database_path):
            return "不可读或不存在"
        try:
            connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
            try:
                if not self.sqlite_table_exists(connection, "stage1_outputs"):
                    return 0
                row = connection.execute("SELECT COUNT(*) FROM stage1_outputs").fetchone()
                return row[0] if row else 0
            finally:
                connection.close()
        except sqlite3.DatabaseError:
            return "不可读"

    def launch_profile(self, profile_name):
        """按账号隔离环境变量后启动 Codex 桌面端。"""
        codex_path = self.get_store_codex_path()
        if not codex_path:
            return

        profile_root = Path(self.config_data.get("profile_root") or DEFAULT_PROFILE_ROOT)
        profile_dir = profile_root / sanitize_profile_name(profile_name)
        appdata_dir = profile_dir / "AppData" / "Roaming"
        localappdata_dir = profile_dir / "AppData" / "Local"
        codex_home_dir = profile_dir / "CodexHome"
        user_data_dir = self.get_user_data_dir(profile_name)

        target_app_dir = profile_dir / PORTABLE_APP_DIR_NAME
        running_commands = read_running_codex_commands()
        if self.is_profile_running(profile_name, running_commands) and portable_app_needs_update(codex_path, target_app_dir):
            messagebox.showwarning(
                "需要关闭账号",
                "微软商店版 Codex 已更新，但该账号正在运行。\n请先关闭该账号窗口，再重新启动以同步新版程序。",
                parent=self,
            )
            return

        for directory in (appdata_dir, localappdata_dir, codex_home_dir, user_data_dir):
            directory.mkdir(parents=True, exist_ok=True)
        ensure_profile_env_file(codex_home_dir)

        env = os.environ.copy()
        env["APPDATA"] = str(appdata_dir)
        env["LOCALAPPDATA"] = str(localappdata_dir)
        env["CODEX_HOME"] = str(codex_home_dir)
        env["CODEX_MULTI_PROFILE"] = profile_name

        try:
            portable_codex_path = prepare_portable_codex_path(codex_path, profile_dir)
            self.prepare_session_sync(codex_home_dir)
            self.prepare_memory_sync(codex_home_dir)
            subprocess.Popen(
                [
                    portable_codex_path,
                    f"--user-data-dir={user_data_dir}",
                ],
                cwd=str(Path(portable_codex_path).parent),
                env=env,
                close_fds=True,
            )
        except Exception as exc:
            messagebox.showerror("启动失败", f"无法启动 Codex：\n{exc}")
            return

        messagebox.showinfo("已启动", f"已用独立环境启动：{profile_name}")
        self.after(1200, self.render_profiles)


def main():
    """运行 Codex 多账号启动器。"""
    if sys.platform != "win32":
        print("此启动器仅用于 Windows。")
        return 1
    app = Launcher()
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
