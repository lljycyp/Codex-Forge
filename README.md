# Codex Forge

Codex Forge 是一个 Windows 桌面端的 Codex 账号、配置和指令工作台。

界面使用 Electron + React，后端能力通过本地 Python 桥接进程提供。

## 功能范围

- 管理多个 Codex 账号资料。
- 查看账号运行状态和额度信息。
- 切换账号时写入当前用户的 `.codex` 目录。
- 编辑当前生效的 `config.toml`。
- 管理 Codex 指令模板。
- 启动 Codex 时执行系统默认的 `codex app`。

当前不会复制 Codex 程序目录，不做会话/记忆同步，也不支持多个账号并发多开。

## 环境要求

- Windows 10 / Windows 11
- Python 3.11 或更高版本
- uv
- Node.js
- yarn
- Bash，Windows 可使用 Git Bash
- 系统默认可执行的 `codex` 命令

检查 Codex 命令：

```bash
codex --version
```

## 初始化

```bash
cd /d/MyObject/CodexForge
export UV_PROJECT_ENVIRONMENT="./python/.venv"
uv sync --dev
yarn install
```

## 开发运行

```bash
yarn dev
```

## 检查

```bash
export UV_PROJECT_ENVIRONMENT="./python/.venv"
uv run python -m py_compile ./python/main.py
yarn tsc --noEmit
```

## 打包

完整打包：

```bash
yarn build
```

分步打包：

```bash
yarn build:backend
yarn build:shell
yarn build:installer
```

打包流程会先用 Cython 编译受保护的 Python 模块，再通过 `python -m PyInstaller` 生成 `resources/main.exe`，最后构建 Electron 桌面壳和 Windows 安装包。

主要产物：

- `resources/main.exe`
- `release/Codex Forge Setup 0.1.0.exe`
