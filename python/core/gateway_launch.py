import json
import mmap
import os
import shutil
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from core.app_server_service import AppServerClient, AppServerRequestError, find_codex_cli_path
from core.auth_service import auth_kind
from core.codex_source import resolve_codex_execution_path
from core.file_lock import _exclusive_file_lock
from core.path_utils import is_reparse_point
from core.profile_service import get_active_codex_dir

OVERRIDE = "CODEX_APP_SERVER_OPENAI_BASE_URL"
BALANCED_FLAG = "--codex-forge-balanced"
BALANCED_CHATGPT_FLAG = "--codex-forge-balanced-chatgpt"
BALANCED_HOME = "codex-home"


def supports_gateway(executable):
    archive = Path(executable).parent / "resources/app.asar"
    if not archive.is_file():
        return False
    with archive.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        return data.find(OVERRIDE.encode()) >= 0


@dataclass
class DesktopLaunch:
    command: list
    cwd: str
    env: dict = field(repr=False)
    profile_name: str
    skin_port: int | None
    native_auth: bool

    def start(self):
        from bridge import commands

        config = commands.load_config()
        lock = commands._get_shared_app_root(config) / ".codex-client-operation.lock"
        with _exclusive_file_lock(lock, timeout_seconds=10):
            if commands._running_codex_count():
                raise ValueError("当前 Codex 正在运行，请先退出再切换启动模式")
            if self.native_auth:
                if auth_kind(commands._read_system_auth()) != "chatgpt":
                    raise ValueError("当前 ChatGPT 登录已变更，请重新启动负载均衡")
                commands._sync_shared_workspace(config, get_active_codex_dir(), commands.get_active_auth_path())
            process = subprocess.Popen(
                self.command,
                cwd=self.cwd,
                env=self.env,
                close_fds=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        result: dict[str, object] = {"pid": process.pid}
        if self.skin_port is not None:
            result["skinSession"] = {
                "profileName": self.profile_name, "port": self.skin_port, "processId": process.pid
            }
        return result


def _login_gateway(home, cli_path, env, url, key):
    login_env = {**env, "CODEX_SQLITE_HOME": str(home)}
    try:
        with AppServerClient(
            home, cli_path, env=login_env, config_args=("-c", 'cli_auth_credentials_store="file"'),
        ) as client:
            client.request("config/batchWrite", {"edits": [
                {"keyPath": "openai_base_url", "value": url, "mergeStrategy": "replace"},
                {"keyPath": "cli_auth_credentials_store", "value": "file", "mergeStrategy": "replace"},
            ], "applyToCurrentSession": True})
            effective = client.request("config/read", {})["config"]
            if effective.get("openai_base_url") != url:
                raise ValueError("网关地址被其他 Codex 配置覆盖，请检查当前配置")
            client.request("account/login/start", {"type": "apiKey", "apiKey": key})
            account = client.request("account/read", {"refreshToken": False}).get("account")
    except AppServerRequestError as exc:
        raise ValueError(f"无法准备 Codex 负载均衡登录（{exc.code}），请检查客户端配置") from None
    except RuntimeError as exc:
        raise ValueError("Codex App Server 未完成负载均衡登录，请检查客户端配置") from exc
    try:
        auth = json.loads((home / "auth.json").read_text("utf-8-sig"))
    except (OSError, ValueError):
        raise ValueError("Codex 未保存 Forge API Key，请检查客户端认证配置") from None
    if (account or {}).get("type") != "apiKey" or not isinstance(auth, dict) or auth.get("OPENAI_API_KEY") != key:
        raise ValueError("Codex 未保存 Forge API Key，请检查客户端认证配置")


def _share_session_dirs(source, target):
    from _winapi import CreateJunction  # type: ignore[attr-defined]

    for name in ("sessions", "archived_sessions"):
        original, link = source / name, target / name
        original.mkdir(exist_ok=True)
        linked = is_reparse_point(link)
        if linked and link.resolve() == original.resolve():
            continue
        if linked or link.exists():
            raise ValueError(f"负载均衡会话路径已被占用：{link}")
        CreateJunction(str(original), str(link))


def prepare_launch(url, certificate, key):
    from bridge import commands

    config = commands.load_config()
    name = config.get("active_profile", "")
    if commands._running_codex_count():
        raise ValueError("当前 Codex 正在运行。请在方便时自行退出，再从首页启动负载均衡。")
    path = Path(commands._resolve_codex_app_source_path(config))
    if not supports_gateway(path):
        raise ValueError("该桌面版本未提供进程级网关配置，请使用支持此功能的 Codex 版本")
    env = os.environ.copy()
    for env_name in (
        "CODEX_THREAD_ID",
        "CODEX_SESSION_ID",
        "CODEX_TOOL_CALL_ID",
        "CODEX_APP_TOOLS_PIPE_PATH",
        "CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY",
    ):
        env.pop(env_name, None)
    home = Path(env.get("CODEX_HOME") or get_active_codex_dir()).resolve()
    settings = commands.db.load_profile_launch_settings(name) if name else {}
    env.update({str(k): str(v) for k, v in (settings.get("env") or {}).items()})
    env = {k: v for k, v in env.items() if k.upper() not in ("CODEX_API_KEY", "OPENAI_API_KEY", "CODEX_ACCESS_TOKEN")}
    config_path = home / "config.toml"
    config_text = config_path.read_text("utf-8-sig") if config_path.is_file() else ""
    settings_toml = tomllib.loads(config_text)
    layer = None
    profile = settings_toml.get("profile")
    if profile:
        if not isinstance(profile, str) or Path(profile).name != profile:
            raise ValueError("当前 Codex 配置的 profile 无效")
        layer = home / (profile + ".config.toml")
        overrides = (
            tomllib.loads(layer.read_text("utf-8-sig"))
            if layer.is_file()
            else settings_toml.get("profiles", {}).get(profile, {})
        )
        if overrides.get("cli_auth_credentials_store", "file") != "file":
            raise ValueError("负载均衡需要独立的文件认证，请检查 Codex profile 中的认证存储设置")
        settings_toml = {**settings_toml, **overrides}
    if settings_toml.get("model_provider", "openai") != "openai":
        raise ValueError("此环境使用自定义模型提供方，请通过负载均衡页面的客户端配置接入")
    # Preserve the selected environment's existing Electron data, cwd and launch options.
    extra = list(map(str, settings.get("args", [])))
    if any(a.startswith(("--user-data-dir", "--remote-debugging-pipe")) for a in extra) or any(
        k.upper() in ("CODEX_HOME", "CODEX_SQLITE_HOME", "CODEX_ELECTRON_USER_DATA_PATH")
        for k in (settings.get("env") or {})
    ):
        raise ValueError("启动参数自定义了数据目录，请先在环境页确认会话目录")
    certificate = Path(certificate)
    gateway_home = certificate.parent.resolve() / BALANCED_HOME
    sqlite_home = Path(settings_toml.get("sqlite_home") or env.get("CODEX_SQLITE_HOME") or home)
    sqlite_home = (home / sqlite_home).resolve()
    native_auth = (
        home == get_active_codex_dir().resolve()
        and settings_toml.get("cli_auth_credentials_store", "file") == "file"
        and settings_toml.get("forced_login_method") != "api"
        and auth_kind(commands._read_system_auth()) == "chatgpt"
    )
    env.update(CODEX_SQLITE_HOME=str(sqlite_home), CODEX_CA_CERTIFICATE=str(certificate))
    env[OVERRIDE] = url
    if native_auth:
        env["CODEX_HOME"] = str(home)
        env["NO_PROXY"] = ",".join(filter(None, (env.get("NO_PROXY"), "127.0.0.1")))
        extra.append(BALANCED_CHATGPT_FLAG)
    else:
        if is_reparse_point(gateway_home) or home == gateway_home or gateway_home in home.parents:
            raise ValueError("负载均衡认证目录与系统会话目录冲突，请检查 CODEX_HOME")
        cli_path = path.parent / "resources" / "codex.exe"
        gateway_home.mkdir(parents=True, exist_ok=True)
        (gateway_home / "config.toml").write_text(config_text, encoding="utf-8")
        if layer:
            if layer.is_file():
                shutil.copyfile(layer, gateway_home / layer.name)
            else:
                (gateway_home / layer.name).unlink(missing_ok=True)
        env["CODEX_HOME"] = str(gateway_home)
        _login_gateway(gateway_home, cli_path if cli_path.is_file() else find_codex_cli_path(), env, url, key)
        home.mkdir(parents=True, exist_ok=True)
        _share_session_dirs(home, gateway_home)
        state_name = ".codex-global-state.json"
        if (home / state_name).is_file() and not (gateway_home / state_name).exists():
            shutil.copyfile(home / state_name, gateway_home / state_name)
    skin_enabled = config.get("codex_skin_enabled")
    port = commands._allocate_codex_skin_port() if skin_enabled else None
    if port is not None:
        extra = commands._append_codex_skin_args(extra, port)
    return DesktopLaunch(
        [str(resolve_codex_execution_path(path)), *extra, BALANCED_FLAG],
        settings.get("workingDir") or str(path.parent),
        env,
        name or commands.SYSTEM_PROFILE_NAME,
        port,
        native_auth,
    )
