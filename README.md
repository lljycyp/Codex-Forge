# Codex Forge

Codex 账号切换 · Auth 管理 · TOML / 指令模板可视化工作台

面向 Windows 桌面端 Codex 的本地管理工具。它把多个 Codex 登录资料、`auth.json`、`config.toml`、指令模板和额度快照集中到一个桌面界面里，切换账号时写入当前用户的 `.codex` 目录并启动 Codex。

![Codex Forge Logo](src/renderer/src/assets/codex-forge-logo.png)

---

## Codex Forge 是什么？

Codex Forge 不是 Codex 的替代品，而是一个本地账号和配置工作台。

它把几个高频操作做成了桌面软件：

- 管理多个 Codex 账号资料。
- 通过浏览器授权、当前默认账号或本地 `auth.json` 新增账号。
- 切换账号时写入当前用户的 `~/.codex/auth.json`。
- 可选择所有账号共享系统 `config.toml`，或为账号保存独立配置。
- 查看和编辑当前生效的 `~/.codex/config.toml`。
- 保存、启用、禁用自定义 Codex 指令模板。
- 查看账号健康状态、运行状态和额度快照。
- 识别并启动本机已安装的 Codex 桌面端 / `codex app`。

当前不会复制 Codex 程序目录，不做会话 Provider 修复，也不支持多个账号并发多开。

## 功能特性

| 功能 | 说明 |
| --- | --- |
| 账号资料管理 | 新增、重命名、删除账号资料，默认保存在 `~/Documents/CodexProfiles`。 |
| 授权导入 | 支持浏览器 OAuth 授权、保存当前默认 Codex 账号、导入本地 `auth.json`。 |
| 一键切换启动 | 切换账号时写入当前用户 `.codex`，并启动默认 Codex。检测到 Codex 正在运行时会要求先关闭。 |
| 额度快照 | 读取账号 Auth 信息并请求 Codex usage 接口，缓存显示各账号额度状态。 |
| TOML 编辑 | 直接查看和保存当前生效的 `config.toml`，保存前自动备份。 |
| 指令模板 | 本地管理 Markdown 指令模板，启用后写入 Codex 配置并更新 `model_instructions_file`。 |
| 诊断信息 | 展示配置路径、账号根目录、Codex 进程、账号资料完整性和日志路径。 |
| Windows 打包 | 使用 Cython + PyInstaller 构建 Python 后端，再用 Electron Builder 生成安装包。 |

## 核心亮点

### 1. 多账号资料隔离

每个账号资料保存自己的登录文件：

```text
~/Documents/CodexProfiles/<账号名>/auth.json
~/Documents/CodexProfiles/<账号名>/config.toml
```

开启“共享系统 config.toml”后，切换账号只替换 `auth.json`，模型、代理等 Codex 配置继续使用系统当前配置。

### 2. Auth 管理

新增账号有三种方式：

- 浏览器授权：打开 OpenAI 授权流程，授权结果只保存到新账号资料目录。
- 保存当前账号：复制当前 `~/.codex/auth.json`。
- 上传 `auth.json`：从本地选择已有 Codex 登录文件导入。

额度刷新时会在必要时刷新登录令牌，并把当前账号的新 Auth 回写到对应账号资料。

### 3. TOML 可视化编辑

Codex Forge 读取当前生效的：

```text
~/.codex/config.toml
```

保存前会校验 TOML 内容，并把旧文件备份到：

```text
%LOCALAPPDATA%/CodexForge/backups/config-toml/
```

### 4. 指令模板管理

指令模板保存在启动器本地目录。启用模板后，Codex Forge 会把模板写入当前 Codex 配置目录，并更新 `config.toml` 中的 `model_instructions_file`。

### 5. Codex 启动来源识别

启动账号时会按顺序识别：

- 已保存的 Codex 桌面程序路径。
- 正在运行的 Codex / Microsoft Store 版 Codex。
- Windows Store 应用启动标识。
- 系统 PATH 中的 `codex` 命令，并执行 `codex app`。

## 技术栈

| 类型 | 技术 |
| --- | --- |
| 桌面框架 | Electron 41 / electron-vite |
| 前端 | React 18 / TypeScript / Vite |
| UI | Ant Design 5 / Tailwind CSS / lucide-react |
| 后端 | Python 3.11 本地桥接进程 |
| 打包 | Cython / PyInstaller / Electron Builder |
| 包管理 | yarn / uv |

## 配置路径

Codex Forge 默认读写 Codex 当前用户配置：

```text
~/.codex/auth.json
~/.codex/config.toml
```

自身配置、日志和缓存默认位于：

```text
%LOCALAPPDATA%/CodexForge/config.json
%LOCALAPPDATA%/CodexForge/logs/launcher.log
%LOCALAPPDATA%/CodexForge/usage_cache.json
```

账号资料默认位于：

```text
~/Documents/CodexProfiles
```

## 环境要求

- Windows 10 / Windows 11
- Python 3.11 或更高版本
- uv
- Node.js
- yarn
- Bash，Windows 可使用 Git Bash
- 已安装 Codex 桌面端，或系统可执行 `codex` 命令

检查 Codex 命令：

```bash
codex --version
```

## 开发运行

```bash
cd /d/MyObject/CodexForge
export UV_PROJECT_ENVIRONMENT="./python/.venv"
uv sync --dev
yarn install
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

```text
resources/main.exe
release/Codex Forge Setup 0.1.0.exe
```
