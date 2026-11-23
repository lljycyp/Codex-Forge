import os
import json
import re
import subprocess
import sys
import ctypes
import ctypes.wintypes
import xml.etree.ElementTree as ET
from pathlib import Path

from core.constants import PORTABLE_APP_DIR_NAME, SOURCE_VERSION_FILE_NAME
from core.path_utils import normalize_path_for_match


def read_running_codex_commands():
    """读取当前所有 Codex 相关进程的命令行。"""
    return normalize_path_for_match(
        "\n".join(process["command_line"] for process in read_running_codex_processes())
    )


def read_running_codex_processes():
    """读取当前所有 Codex 客户端主进程。"""
    script = r"""
$processes = Get-CimInstance Win32_Process -Filter "Name = 'ChatGPT.exe' OR Name = 'Codex.exe'"
@($processes | Select-Object Name, ProcessId, ExecutablePath, CommandLine) | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    items = payload if isinstance(payload, list) else [payload]
    candidates = [
        {
            "name": str(item.get("Name") or ""),
            "pid": int(item.get("ProcessId") or 0),
            "executable_path": str(item.get("ExecutablePath") or ""),
            "command_line": str(item.get("CommandLine") or ""),
        }
        for item in items
        if isinstance(item, dict) and item.get("ProcessId") and item.get("CommandLine")
    ]
    return [process for process in candidates if _is_client_main_process(process)]


def _is_client_main_process(process):
    """排除 Chromium 子进程和新版内置 codex app-server。"""
    name = str(process.get("name") or "").lower()
    command_line = str(process.get("command_line") or "").lower()
    executable_path = normalize_path_for_match(process.get("executable_path") or "")
    if name not in ("chatgpt.exe", "codex.exe"):
        return False
    if "--type=" in command_line or " app-server" in command_line:
        return False
    return not (name == "codex.exe" and "\\resources\\codex.exe" in executable_path)


def find_windowsapps_codex_path():
    """自动查找微软商店版 Codex 主程序路径。"""
    running_path = find_running_codex_path()
    if running_path and is_windowsapps_codex_path(running_path):
        return running_path
    return find_windowsapps_codex_path_by_package() or find_windowsapps_codex_path_by_scan()


def find_windowsapps_codex_path_by_package():
    """按新版商店包结构优先定位 ChatGPT.exe。"""
    return _find_appx_client_path() or _find_windowsapps_client_path(("OpenAI.Codex_", "OpenAI.ChatGPT_"))


def _find_appx_client_path():
    """通过当前用户 AppX Manifest 获取真实主程序路径。"""
    if os.name != "nt":
        return ""
    script = r"""
$result = @()
foreach ($packageName in @('OpenAI.Codex', 'OpenAI.ChatGPT')) {
  $package = Get-AppxPackage -Name $packageName | Sort-Object Version -Descending | Select-Object -First 1
  if ($null -eq $package) { continue }
  $manifest = $package | Get-AppxPackageManifest
  foreach ($application in @($manifest.Package.Applications.Application)) {
    if ($null -eq $application -or -not $application.Executable) { continue }
    $path = Join-Path $package.InstallLocation $application.Executable
    if (Test-Path -LiteralPath $path) {
      $result += [pscustomobject]@{ Path = $path; Version = $package.Version.ToString() }
    }
  }
}
@($result) | ConvertTo-Json -Compress
"""
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True,
            text=True,
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        return ""
    if result.returncode != 0 or not result.stdout.strip():
        return ""
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return ""
    items = payload if isinstance(payload, list) else [payload]
    for item in items:
        path = Path(str(item.get("Path") or "")) if isinstance(item, dict) else Path()
        if path.is_file() and path.name.lower() in ("chatgpt.exe", "codex.exe"):
            return str(path)
    return ""


def find_windowsapps_codex_path_by_scan():
    """在 WindowsApps 目录里兜底查找已知客户端入口。"""
    return _find_windowsapps_client_path(("codex", "chatgpt", "openai"))


def _find_windowsapps_client_path(package_markers):
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
        if not any(marker.lower() in lowered_name for marker in package_markers):
            continue
        for relative_path in ("app/ChatGPT.exe", "app/Codex.exe", "ChatGPT.exe", "Codex.exe"):
            candidate = child / relative_path
            if candidate.exists():
                candidates.append(candidate)
                break

    if not candidates:
        return ""
    candidates.sort(
        key=lambda path: (path.name.lower() == "chatgpt.exe", path.stat().st_mtime_ns),
        reverse=True,
    )
    return str(candidates[0])


def get_windowsapps_dir():
    """获取系统微软商店应用安装目录。"""
    program_files = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"
    return Path(program_files) / "WindowsApps"


def resolve_codex_execution_path(codex_path):
    """商店版使用包专属执行别名，让直接启动也保留任务栏所需的应用身份。"""
    path = Path(codex_path)
    package_dir = next(
        (
            parent for parent in path.parents
            if parent.parent.name.lower() == "windowsapps"
            and parent.name.lower().startswith(("openai.codex_", "openai.chatgpt_"))
        ),
        None,
    )
    if package_dir is None:
        return path
    try:
        manifest = ET.parse(package_dir / "AppxManifest.xml").getroot()
        identity = manifest.find("{*}Identity")
        if identity is None:
            return path
        family_name = f"{identity.attrib['Name']}_{package_dir.name.rsplit('_', 1)[-1]}"
        local_appdata = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        alias_dir = local_appdata / "Microsoft" / "WindowsApps" / family_name
        executable = path.relative_to(package_dir).as_posix().lower()
        for application in manifest.findall("./{*}Applications/{*}Application"):
            if application.get("Executable", "").replace("\\", "/").lower() != executable:
                continue
            for alias in application.findall(".//{*}AppExecutionAlias/{*}ExecutionAlias"):
                alias_name = alias.get("Alias")
                if alias_name and (alias_path := alias_dir / alias_name).is_file():
                    return alias_path
    except (OSError, ET.ParseError, KeyError):
        pass
    return path


def is_windowsapps_codex_path(path):
    """判断路径是否为微软商店应用目录里的客户端主程序。"""
    path = Path(path)
    return (
        path.exists()
        and path.name.lower() in ("chatgpt.exe", "codex.exe")
        and "windowsapps" in normalize_path_for_match(path)
    )


def find_running_codex_path():
    """从正在运行的客户端主进程读取真实程序路径。"""
    for process in read_running_codex_processes():
        path = process.get("executable_path") or ""
        if path and Path(path).exists():
            return path
    return ""


def read_source_signature(target_app_dir):
    """读取共享客户端副本记录的安装源版本信息。"""
    version_path = Path(target_app_dir) / SOURCE_VERSION_FILE_NAME
    if not version_path.exists():
        return {}
    try:
        return json.loads(version_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def find_latest_portable_app_dir(profile_dir):
    """定位旧版客户端副本中的 App Server。"""
    profile_dir = Path(profile_dir)
    candidates = [
        profile_dir / PORTABLE_APP_DIR_NAME,
        *profile_dir.glob(f"{PORTABLE_APP_DIR_NAME}-*"),
        profile_dir / "ChatGPTPortableApp",
    ]
    ready_dirs = [
        directory
        for directory in candidates
        if (directory / "ChatGPT.exe").is_file() or (directory / "Codex.exe").is_file()
    ]
    if not ready_dirs:
        return profile_dir / PORTABLE_APP_DIR_NAME

    def sort_key(directory):
        signature = read_source_signature(directory)
        version = tuple(int(part) for part in re.findall(r"\d+", str(signature.get("package_version") or "")))
        try:
            modified_ns = directory.stat().st_mtime_ns
        except OSError:
            modified_ns = 0
        return version, modified_ns

    return max(ready_dirs, key=sort_key)


def request_process_close(pid):
    """向指定进程拥有的顶层窗口发送 WM_CLOSE。"""
    if sys.platform != "win32":
        return 0
    user32 = ctypes.windll.user32
    wm_close = 0x0010
    matched = 0
    callback_type = ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

    def callback(hwnd, _lparam):
        nonlocal matched
        process_id = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == int(pid):
            user32.PostMessageW(hwnd, wm_close, 0, 0)
            matched += 1
        return True

    user32.EnumWindows(callback_type(callback), 0)
    return matched
