"""Prepare a dedicated desktop home without copying any ChatGPT credentials."""

import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

from core.app_server_service import find_codex_cli_path
from core.codex_source import read_running_codex_processes, find_windowsapps_codex_path
from core.constants import CONFIG_DIR
from core.profile_service import get_active_config_path


def prepare_client(root, base_url, key):
    root = Path(root).resolve()
    home = root / "CodexHome"
    user_data = root / "UserData"
    for directory in (home, user_data, root / "AppData/Roaming", root / "AppData/Local"):
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.resolve().is_relative_to(root):
            raise ValueError("独立客户端目录不能指向外部目录")
    config_path = home / "config.toml"
    if not config_path.resolve().is_relative_to(root):
        raise ValueError("独立客户端配置不能指向外部文件")
    auth = home / "auth.json"
    if auth.exists():
        saved = json.loads(auth.read_text(encoding="utf-8-sig"))
        if saved.get("tokens"):
            raise ValueError("独立客户端已登录 ChatGPT 账号，请先在该独立客户端退出登录")
    # Read only the selected model, never copy auth, hooks, MCP or account settings.
    source = config_path if config_path.exists() else get_active_config_path()
    original = source.read_text(encoding="utf-8-sig") if source.exists() else ""
    config = tomllib.loads(original)
    model = config.get("model") or "gpt-6-astra"
    content = f'''# Managed by Codex Forge: dedicated load-balancing client.
model = {json.dumps(model)}
model_provider = "forge"
model_reasoning_effort = "low"
cli_auth_credentials_store = "file"

[model_providers.forge]
name = "Forge"
base_url = {json.dumps(base_url)}
env_key = "FORGE_GATEWAY_KEY"
wire_api = "responses"
requires_openai_auth = false
supports_websockets = false
request_max_retries = 0
stream_max_retries = 0
'''
    if config_path.exists():
        provider = config.get("model_providers", {}).get("forge", {})
        if (config.get("model_provider") != "forge" or provider.get("env_key") != "FORGE_GATEWAY_KEY"
                or provider.get("requires_openai_auth") is not False):
            raise ValueError("独立客户端的 Forge 服务配置已被修改，请恢复配置后启动")
        # Keep settings written by the desktop (including sandbox setup and model choice).
        section = re.search(r"(?m)^\[model_providers\.forge\][^\n]*\n([^\[]*)", original)
        if not section:
            raise ValueError("无法更新独立客户端的 Forge 服务地址")
        updated, count = re.subn(r"(?m)^base_url\s*=.*$", f"base_url = {json.dumps(base_url)}", section.group(0))
        if count != 1:
            raise ValueError("无法更新独立客户端的 Forge 服务地址")
        content = original[:section.start()] + updated + original[section.end():]
        if tomllib.loads(content)["model_providers"]["forge"]["base_url"] != base_url:
            raise ValueError("独立客户端服务地址校验失败")
    config_path.write_text(content, encoding="utf-8")
    env = os.environ.copy()
    # A Forge started from a Codex terminal must not pass its parent's task/control pipe.
    for name in list(env):
        if name.upper().startswith("CODEX_") or name.upper() in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
            env.pop(name)
    env.update(CODEX_HOME=str(home), CODEX_ELECTRON_USER_DATA_PATH=str(user_data),
               HOME=str(root), USERPROFILE=str(root),
               APPDATA=str(root / "AppData/Roaming"), LOCALAPPDATA=str(root / "AppData/Local"),
               FORGE_GATEWAY_KEY=key, CODEX_MULTI_PROFILE="Forge load balancing")
    return home, user_data, env


def launch_client(config, base_url, key):
    root = CONFIG_DIR / "load-balancer-client"
    processes = read_running_codex_processes()
    marker = str(root / "UserData").replace("/", "\\").lower()
    if any(marker in p["command_line"].replace("/", "\\").lower() for p in processes):
        return {"alreadyRunning": True, "home": str(root / "CodexHome")}
    candidates = [Path(config.get("codex_path") or "")]
    candidates.extend(Path(p["executable_path"]) for p in processes)
    executable = next((p for p in candidates if p.is_file() and (p.parent / "resources/app.asar").is_file()), None)
    if executable is None:
        detected = find_windowsapps_codex_path()
        executable = Path(detected) if detected else None
    if executable is None or not executable.is_file():
        raise ValueError("未找到 Codex 桌面客户端，请先在启动设置中选择客户端")
    cli = find_codex_cli_path()
    home, user_data, env = prepare_client(root, base_url, key)
    env["CODEX_CLI_PATH"] = str(cli)
    process = subprocess.Popen([str(executable), f"--user-data-dir={user_data}"],
        cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, close_fds=True, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return {"alreadyRunning": False, "home": str(home), "processId": process.pid}
