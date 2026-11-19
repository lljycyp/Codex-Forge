import mmap
import os
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from core.codex_source import resolve_codex_execution_path
from core.profile_service import get_active_codex_dir

OVERRIDE = "CODEX_APP_SERVER_OPENAI_BASE_URL"


def supports_gateway(executable):
    archive = Path(executable).parent / "resources/app.asar"
    if not archive.is_file():
        return False
    with archive.open("rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
        return data.find(OVERRIDE.encode()) >= 0


@dataclass
class DesktopLaunch:
    auth_path: Path
    command: list
    cwd: str
    env: dict = field(repr=False)
    profile_name: str
    skin_port: int | None

    def start(self):
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


def prepare_launch(url, certificate):
    from bridge import commands

    config = commands.load_config()
    name = config.get("active_profile", "")
    multi = config.get("launch_mode") == "multi"
    if multi and name not in config.get("profiles", []):
        raise ValueError("请先在账号管理选择要打开的客户端环境")
    if commands._is_profile_running(config, name) if multi else commands._running_codex_count():
        raise ValueError("当前 Codex 正在运行。请在方便时自行退出，再从首页启动负载均衡。")
    path = Path(commands._resolve_codex_app_source_path(config))
    if not supports_gateway(path):
        raise ValueError("该桌面版本未提供进程级网关配置，请使用支持此功能的 Codex 版本")
    args = []
    env = os.environ.copy()
    for key in (
        "CODEX_THREAD_ID",
        "CODEX_SESSION_ID",
        "CODEX_TOOL_CALL_ID",
        "CODEX_APP_TOOLS_PIPE_PATH",
        "CODEX_TASK_WORKSPACE_VERIFYING_IDENTITY",
    ):
        env.pop(key, None)
    home = Path(env.get("CODEX_HOME") or get_active_codex_dir())
    settings = commands.db.load_profile_launch_settings(name) if name else {}
    env.update({str(k): str(v) for k, v in (settings.get("env") or {}).items()})
    if multi:
        folder = commands._get_profile_dir(config, name)
        home = folder / "CodexHome"
        if not (home / "auth.json").exists():
            commands.prepare_profile_codex_home(folder)
        env.update(
            APPDATA=str(folder / "AppData/Roaming"),
            LOCALAPPDATA=str(folder / "AppData/Local"),
            CODEX_MULTI_PROFILE=name,
            CODEX_ELECTRON_USER_DATA_PATH=str(folder / "AppData/Roaming/Codex"),
        )
        args.append("--user-data-dir=" + str(commands._get_user_data_dir(config, name)))
    conf = home / "config.toml"
    settings_toml = tomllib.loads(conf.read_text("utf-8-sig")) if conf.is_file() else {}
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
        settings_toml = {**settings_toml, **overrides}
    if settings_toml.get("model_provider", "openai") != "openai":
        raise ValueError("此环境使用自定义模型提供方，请通过负载均衡页面的客户端配置接入")
    if not (home / "auth.json").is_file():
        raise ValueError("请先在此客户端环境完成登录")
    env.update(CODEX_HOME=str(home), CODEX_CA_CERTIFICATE=str(certificate))
    env[OVERRIDE] = url
    # Preserve the selected environment's existing Electron data, cwd and launch options.
    extra = list(map(str, settings.get("args", [])))
    if any(a.startswith(("--user-data-dir", "--remote-debugging-pipe")) for a in extra) or any(
        k in (settings.get("env") or {})
        for k in ("CODEX_HOME", "CODEX_SQLITE_HOME", "CODEX_ELECTRON_USER_DATA_PATH")
    ):
        raise ValueError("启动参数自定义了数据目录，请先在环境页确认会话目录")
    skin_port = None
    if config.get("codex_skin_enabled"):
        skin_port = commands._allocate_codex_skin_port()
        extra = commands._append_codex_skin_args(extra, skin_port)
    return DesktopLaunch(
        home / "auth.json",
        [str(resolve_codex_execution_path(path)), *args, *extra],
        settings.get("workingDir") or str(path.parent),
        env,
        name or commands.SYSTEM_PROFILE_NAME,
        skin_port,
    )
