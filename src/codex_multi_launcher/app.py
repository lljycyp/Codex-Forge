import json
import os
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog


APP_NAME = "Codex 多账号启动器"
ICON_FILE_NAME = "app.ico"
CONFIG_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CodexMultiLauncher"
CONFIG_PATH = CONFIG_DIR / "config.json"
DEFAULT_PROFILE_ROOT = Path.home() / "Documents" / "CodexProfiles"
PORTABLE_APP_DIR_NAME = "CodexPortableApp"
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
    """读取启动器配置；不存在时返回默认配置。"""
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return default_config()
    return default_config()


def default_config():
    """生成默认配置，首次进入不预置任何账号。"""
    return {
        "codex_path": "",
        "profile_root": str(DEFAULT_PROFILE_ROOT),
        "profiles": [],
        "imported_original_profile": "",
    }


def save_config(config):
    """保存启动器配置，便于下次双击直接使用。"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


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


def find_common_codex_path():
    """尝试从常见安装位置和正在运行的进程寻找 Codex 主程序。"""
    running_path = find_running_codex_path()
    if running_path:
        return running_path

    local_app_data = Path(os.environ.get("LOCALAPPDATA", ""))
    program_files = [
        Path(os.environ.get("ProgramFiles", "")),
        Path(os.environ.get("ProgramFiles(x86)", "")),
    ]
    candidates = [
        local_app_data / "Programs" / "Codex" / "Codex.exe",
        local_app_data / "Programs" / "OpenAI Codex" / "Codex.exe",
        local_app_data / "Codex" / "Codex.exe",
    ]
    for root in program_files:
        candidates.extend(
            [
                root / "Codex" / "Codex.exe",
                root / "OpenAI Codex" / "Codex.exe",
            ]
        )
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return ""


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


def get_portable_codex_path(source_codex_path, profile_dir):
    """为每个账号准备独立 Codex 程序副本，减少程序运行状态共享。"""
    source_app_dir = Path(source_codex_path).parent
    target_app_dir = profile_dir / PORTABLE_APP_DIR_NAME
    target_codex_path = target_app_dir / "Codex.exe"
    if paths_equal(source_app_dir, target_app_dir):
        return str(Path(source_codex_path))
    if target_codex_path.exists():
        return str(target_codex_path)

    target_app_dir.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source_app_dir, target_app_dir, dirs_exist_ok=True)
    return str(target_codex_path)


class Launcher(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("760x430")
        self.resizable(False, False)
        self.set_window_icon()
        self.config_data = load_config()
        if not self.config_data.get("codex_path"):
            self.config_data["codex_path"] = find_common_codex_path()
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
        """构建主界面，提供路径选择、账号启动和账号新增。"""
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
        tk.Label(path_row, text="Codex 程序：", font=("Microsoft YaHei UI", 9)).pack(side="left")
        self.path_var = tk.StringVar(value=self.config_data.get("codex_path", ""))
        path_entry = tk.Entry(path_row, textvariable=self.path_var)
        path_entry.pack(side="left", fill="x", expand=True, padx=(6, 8))
        tk.Button(path_row, text="选择", command=self.choose_codex_path, width=8).pack(side="right")

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
        tk.Button(action_row, text="打开配置目录", command=self.open_config_dir, width=14).pack(side="left", padx=(8, 0))
        tk.Button(action_row, text="退出", command=self.destroy, width=10).pack(side="right")

    def render_profiles(self):
        """刷新账号按钮列表。"""
        for child in self.profile_frame.winfo_children():
            child.destroy()
        profiles = self.config_data.get("profiles", [])
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
            is_running = self.is_profile_running(name, running_commands)
            row = tk.Frame(self.profile_frame)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=f"{index}. {name}", anchor="w", font=("Microsoft YaHei UI", 10)).pack(
                side="left", fill="x", expand=True
            )
            status_text = "运行中" if is_running else "未运行"
            status_color = "#16803c" if is_running else "#666666"
            tk.Label(row, text=status_text, fg=status_color, width=8, font=("Microsoft YaHei UI", 9)).pack(
                side="right", padx=(0, 8)
            )
            tk.Button(row, text="删除", command=lambda n=name: self.delete_profile(n), width=8).pack(side="right")
            tk.Button(row, text="清除登录", command=lambda n=name: self.clear_profile_login(n), width=9).pack(
                side="right", padx=(0, 8)
            )
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

    def choose_codex_path(self):
        """让用户选择 Codex 主程序路径，并写入配置。"""
        selected = filedialog.askopenfilename(
            title="选择 Codex.exe",
            filetypes=[("可执行文件", "*.exe"), ("所有文件", "*.*")],
        )
        if selected:
            self.config_data["codex_path"] = selected
            self.path_var.set(selected)
            save_config(self.config_data)

    def add_profile(self):
        """新增一个账号入口。"""
        name = simpledialog.askstring("新增账号", "请输入账号名称，例如：工作号、个人号：", parent=self)
        if not name:
            return
        name = self.validate_new_profile_name(name)
        if not name:
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

        if not copied_any:
            try:
                if profile_dir.exists():
                    shutil.rmtree(profile_dir)
            except Exception:
                pass
            messagebox.showwarning("未找到原本账号", "没有找到可导入的 Codex 默认数据目录。")
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

    def clear_profile_login(self, profile_name):
        """清除指定账号的登录态和网页会话缓存。"""
        running_commands = read_running_codex_commands()
        if self.is_profile_running(profile_name, running_commands):
            messagebox.showwarning(
                "账号正在运行",
                "请先关闭该账号对应的 Codex 窗口，再清除登录信息。",
                parent=self,
            )
            return

        confirmed = messagebox.askyesno(
            "确认清除登录",
            f"确定清除“{profile_name}”的登录信息吗？\n\n清除后该账号下次启动需要重新登录。",
            parent=self,
        )
        if not confirmed:
            return

        profile_dir = self.get_profile_dir(profile_name)
        targets = [
            profile_dir / "CodexHome" / "auth.json",
            profile_dir / "AppData" / "Roaming" / "Codex" / "Cookies",
            profile_dir / "AppData" / "Roaming" / "Codex" / "Cookies-journal",
            profile_dir / "AppData" / "Roaming" / "Codex" / "Login Data",
            profile_dir / "AppData" / "Roaming" / "Codex" / "Login Data-journal",
            profile_dir / "AppData" / "Roaming" / "Codex" / "Local Storage",
            profile_dir / "AppData" / "Roaming" / "Codex" / "Session Storage",
            profile_dir / "AppData" / "Roaming" / "Codex" / "Network",
            profile_dir / "AppData" / "Roaming" / "Codex" / "web" / "Codex" / "Default" / "Cookies",
            profile_dir / "AppData" / "Roaming" / "Codex" / "web" / "Codex" / "Default" / "Cookies-journal",
            profile_dir / "AppData" / "Roaming" / "Codex" / "web" / "Codex" / "Default" / "Login Data",
            profile_dir / "AppData" / "Roaming" / "Codex" / "web" / "Codex" / "Default" / "Login Data-journal",
            profile_dir / "AppData" / "Roaming" / "Codex" / "web" / "Codex" / "Default" / "Local Storage",
            profile_dir / "AppData" / "Roaming" / "Codex" / "web" / "Codex" / "Default" / "Session Storage",
            profile_dir / "AppData" / "Roaming" / "Codex" / "web" / "Codex" / "Default" / "IndexedDB",
            profile_dir / "AppData" / "Roaming" / "Codex" / "web" / "Codex" / "Default" / "Network",
            profile_dir / "AppData" / "Roaming" / "Codex" / "web" / "Codex" / "Default" / "WebStorage",
        ]

        failed = []
        for target in targets:
            if not target.exists():
                continue
            try:
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink()
            except Exception:
                failed.append(str(target))

        if failed:
            messagebox.showwarning(
                "部分清理失败",
                "部分登录文件可能仍被占用，请关闭对应 Codex 后重试。",
                parent=self,
            )
        else:
            messagebox.showinfo("已清除", f"已清除“{profile_name}”的登录信息。", parent=self)

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

    def open_config_dir(self):
        """打开启动器配置目录，方便用户查看生成的配置文件。"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        os.startfile(str(CONFIG_DIR))

    def launch_profile(self, profile_name):
        """按账号隔离环境变量后启动 Codex 桌面端。"""
        codex_path = self.path_var.get().strip('" ')
        if not codex_path or not Path(codex_path).exists():
            messagebox.showwarning("需要选择程序", "请先选择 Codex.exe 的实际路径。")
            self.choose_codex_path()
            codex_path = self.path_var.get().strip('" ')
            if not codex_path or not Path(codex_path).exists():
                return

        self.config_data["codex_path"] = codex_path
        save_config(self.config_data)

        profile_root = Path(self.config_data.get("profile_root") or DEFAULT_PROFILE_ROOT)
        profile_dir = profile_root / sanitize_profile_name(profile_name)
        appdata_dir = profile_dir / "AppData" / "Roaming"
        localappdata_dir = profile_dir / "AppData" / "Local"
        codex_home_dir = profile_dir / "CodexHome"
        user_data_dir = self.get_user_data_dir(profile_name)

        for directory in (appdata_dir, localappdata_dir, codex_home_dir, user_data_dir):
            directory.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["APPDATA"] = str(appdata_dir)
        env["LOCALAPPDATA"] = str(localappdata_dir)
        env["CODEX_HOME"] = str(codex_home_dir)
        env["CODEX_MULTI_PROFILE"] = profile_name

        try:
            portable_codex_path = get_portable_codex_path(codex_path, profile_dir)
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
