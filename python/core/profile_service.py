import shutil

from core.constants import DEFAULT_CODEX_ENV_PATH


def ensure_profile_env_file(codex_home_dir):
    """确保账号 CodexHome 里有默认 .env；已有账号专属配置时不覆盖。"""
    target_env_path = codex_home_dir / ".env"
    if target_env_path.exists() or not DEFAULT_CODEX_ENV_PATH.exists():
        return
    codex_home_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(DEFAULT_CODEX_ENV_PATH, target_env_path)

