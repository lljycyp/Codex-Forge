# CodexMultiLauncher

CodexMultiLauncher 现在定位为 Windows 桌面端的 Codex 多账号切换器。

当前项目使用 Electron + React 界面，并通过 Python 桥接命令调用本地能力。

核心模型：

- 使用系统默认安装的 Codex 程序。
- 每个账号只保存 `auth.json` 和 `config.toml`。
- 切换账号时写入当前用户的 `.codex` 目录。
- 启动时执行 `codex app`。
- 不复制 Codex 程序目录。
- 不做会话同步和记忆同步。
- 不支持多个账号并发多开。

## 环境要求

- Windows 10 / Windows 11
- Python 3.11 或更高版本
- uv
- Node.js
- yarn
- Bash，Windows 可使用 Git Bash
- 系统默认可执行的 `codex` 命令

检查默认 Codex 命令：

```bash
codex --version
```

## 初始化环境

```bash
cd /d/MyObject/CodexMultiLauncher
export UV_PROJECT_ENVIRONMENT="./python/.venv"
uv sync
yarn install
```

安装开发和打包依赖：

```bash
export UV_PROJECT_ENVIRONMENT="./python/.venv"
uv sync --dev
```

## 运行源码

```bash
yarn dev
```

## 语法检查

```bash
export UV_PROJECT_ENVIRONMENT="./python/.venv"
uv run python -m py_compile ./python/main.py
yarn build
```

## 打包

```bash
yarn build
```

该命令会生成 Python 桥接后端、Electron 桌面壳和 Windows 安装包。

## 文档

- [账号切换重构方案](docs/账号切换重构方案.md)
- [使用说明](docs/使用说明.md)
- [开发打包说明](docs/开发打包说明.md)
