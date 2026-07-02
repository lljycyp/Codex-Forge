import os
import shutil
import subprocess
import sys
import ctypes
import ctypes.wintypes
from pathlib import Path

from core.path_utils import normalize_path_for_match


def read_running_codex_commands():
    """读取当前所有 Codex 相关进程的命令行。"""
    return normalize_path_for_match(
        "\n".join(process["command_line"] for process in read_running_codex_processes())
    )


def read_running_codex_processes():
    """读取当前所有 Codex 相关进程的 PID 和命令行。"""
    command = [
        "wmic",
        "process",
        "where",
        "(name='Codex.exe' or name='codex.exe')",
        "get",
        "CommandLine,ProcessId",
        "/value",
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
        return []
    processes = []
    current = {}
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        key, separator, value = line.partition("=")
        if separator != "=":
            continue
        if key == "CommandLine":
            if current.get("command_line") and current.get("pid"):
                processes.append(current)
                current = {}
            current["command_line"] = value.strip()
        elif key == "ProcessId":
            try:
                current["pid"] = int(value.strip())
            except ValueError:
                pass
    if current.get("command_line") and current.get("pid"):
        processes.append(current)
    return processes


def find_windowsapps_codex_path():
    """自动查找微软商店版 Codex 主程序路径。"""
    running_path = find_running_codex_path()
    if running_path and is_windowsapps_codex_path(running_path):
        return running_path
    return find_windowsapps_codex_path_by_scan()


def find_windowsapps_codex_path_by_package():
    """保留兼容入口；当前不再通过系统脚本查询应用包信息。"""
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
        "wmic",
        "process",
        "where",
        "(name='Codex.exe' or name='codex.exe')",
        "get",
        "ExecutablePath",
        "/value",
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
    for line in result.stdout.splitlines():
        if not line.startswith("ExecutablePath="):
            continue
        path = line.partition("=")[2].strip()
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
    try:
        return read_windows_file_version(Path(path))
    except Exception:
        return ""


class VS_FIXEDFILEINFO(ctypes.Structure):
    _fields_ = [
        ("dwSignature", ctypes.wintypes.DWORD),
        ("dwStrucVersion", ctypes.wintypes.DWORD),
        ("dwFileVersionMS", ctypes.wintypes.DWORD),
        ("dwFileVersionLS", ctypes.wintypes.DWORD),
        ("dwProductVersionMS", ctypes.wintypes.DWORD),
        ("dwProductVersionLS", ctypes.wintypes.DWORD),
        ("dwFileFlagsMask", ctypes.wintypes.DWORD),
        ("dwFileFlags", ctypes.wintypes.DWORD),
        ("dwFileOS", ctypes.wintypes.DWORD),
        ("dwFileType", ctypes.wintypes.DWORD),
        ("dwFileSubtype", ctypes.wintypes.DWORD),
        ("dwFileDateMS", ctypes.wintypes.DWORD),
        ("dwFileDateLS", ctypes.wintypes.DWORD),
    ]


def read_windows_file_version(path):
    """通过 Windows Version API 读取文件版本号。"""
    if sys.platform != "win32":
        return ""
    version = ctypes.windll.version
    file_path = str(path)
    handle = ctypes.wintypes.DWORD()
    size = version.GetFileVersionInfoSizeW(file_path, ctypes.byref(handle))
    if not size:
        return ""

    buffer = ctypes.create_string_buffer(size)
    if not version.GetFileVersionInfoW(file_path, 0, size, buffer):
        return ""

    value = ctypes.wintypes.LPVOID()
    value_size = ctypes.wintypes.UINT()
    if not version.VerQueryValueW(buffer, "\\", ctypes.byref(value), ctypes.byref(value_size)):
        return ""
    if value_size.value < ctypes.sizeof(VS_FIXEDFILEINFO):
        return ""

    info = ctypes.cast(value, ctypes.POINTER(VS_FIXEDFILEINFO)).contents
    return ".".join(
        str(part)
        for part in (
            info.dwFileVersionMS >> 16,
            info.dwFileVersionMS & 0xFFFF,
            info.dwFileVersionLS >> 16,
            info.dwFileVersionLS & 0xFFFF,
        )
    )
