import os
import subprocess
import sys
from pathlib import Path

from core.profile_service import get_active_codex_dir


CA_VARIABLE = "CODEX_CA_CERTIFICATE"
LAN_CERTIFICATE = Path("forge-lan") / "forge-gateway-ca.pem"


def _windows_env(name, *, machine=False):
    if os.name != "nt":
        return None
    import winreg

    hive, key = (
        (winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment")
        if machine else (winreg.HKEY_CURRENT_USER, "Environment")
    )
    try:
        with winreg.OpenKey(hive, key) as settings:
            value, kind = winreg.QueryValueEx(settings, name)
    except FileNotFoundError:
        return None
    if isinstance(value, str):
        return winreg.ExpandEnvironmentStrings(value) if kind == winreg.REG_EXPAND_SZ else value
    return None


def _lan_home():
    return Path(_windows_env("CODEX_HOME") or os.environ.get("CODEX_HOME") or get_active_codex_dir()).resolve()


def account_client_env(env):
    """Use the current Windows CA setting when the process lacks it or retains a Forge LAN CA."""
    env = dict(env)
    inherited = env.get(CA_VARIABLE)
    inherited_path = Path(inherited) if inherited else None
    if inherited_path and (
        inherited_path.name.lower() != LAN_CERTIFICATE.name
        or inherited_path.parent.name.lower() != LAN_CERTIFICATE.parent.name
    ):
        return env
    current = _windows_env(CA_VARIABLE) or _windows_env(CA_VARIABLE, machine=True)
    if current and Path(current).is_file():
        env[CA_VARIABLE] = current
    elif inherited_path:
        home = _lan_home()
        if not inherited_path.is_file() or (
            inherited_path.resolve() == home / LAN_CERTIFICATE
            and not (home / "forge-lan" / "settings.json").is_file()
        ):
            env.pop(CA_VARIABLE)
    return env


def restore_lan_client():
    home = _lan_home()
    if not (home / "forge-lan" / "settings.json").is_file():
        return
    resources = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2] / "resources"
    script = resources / "forge-lan-config.ps1"
    if not script.is_file():
        raise RuntimeError("未找到 Forge 网关复原脚本")
    powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        result = subprocess.run(
            [str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(script), "-Restore"],
            env=account_client_env(os.environ),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=90,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("等待局域网网关设置复原超时，请重试") from exc
    if result.returncode != 0:
        raise RuntimeError(result.stdout.strip() or result.stderr.strip() or "复原脚本执行失败")
