<p align="center">
  <a href="README.md">简体中文</a> |
  <a href="README.en.md">English</a>
</p>

<p align="center">
  <img src="src/renderer/src/assets/codex-forge-logo.png" alt="Codex Forge Logo" width="150" />
</p>

<h1 align="center">Codex Forge</h1>

<p align="center">
  <b>Codex 多账号多开 · Auth 管理 · TOML / 指令模板可视化工作台</b>
</p>

<p align="center">
  面向 Windows 桌面端 Codex 的本地多账号与多开管理工具。它将多个 Codex 登录资料、<code>auth.json</code>、<code>config.toml</code>、指令模板和额度快照集中到一个桌面界面中，既可切换账号后启动 Codex，也可用隔离环境同时多开多个 Codex 客户端。
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-Windows-555" alt="platform" />
  <img src="https://img.shields.io/badge/built%20with-Electron%2041-4B8BBE?logo=electron&logoColor=white" alt="electron" />
  <img src="https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white" alt="python" />
</p>

<p align="center">
  <img src="https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=white" />
  <img src="https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white" />
  <img src="https://img.shields.io/badge/Vite-Ready-646CFF?logo=vite&logoColor=white" />
  <img src="https://img.shields.io/badge/Tailwind-CSS-38B2AC?logo=tailwind-css&logoColor=white" />
</p>

---

## 📖 简介

**Codex Forge** 并非 Codex 的替代品，而是一个强大的**本地多账号、多开与配置工作台**。它将日常高频的终端操作转化为直观的桌面应用功能：

- ✨ **多账号管理**：集中管理多个 Codex 账号资料。
- 🔑 **灵活授权**：支持通过浏览器授权、保存当前默认账号，或导入本地 `auth.json` 来新增账号。
- 🔄 **无缝切换**：切换账号时自动写入当前用户的 `~/.codex/auth.json`。
- 🛡️ **配置隔离**：账号切换模式固定使用系统 `~/.codex/config.toml`；多开隔离模式使用账号 `CodexHome/config.toml`。
- 🛠️ **可视化编辑**：提供查看和编辑当前生效的 `~/.codex/config.toml` 的可视化界面。
- 📝 **指令模板**：把常用提示词保存成 Markdown 模板，一键切换 Codex 的全局行为设定。
- 📊 **状态监控**：实时查看账号健康状态、运行状态以及额度快照。
- 🚀 **可选启动模式**：支持稳定的账号切换模式，也支持多开隔离模式并发启动多个 Codex 客户端。

## 🖼️ 软件预览

<p align="center">
  <img src="docs/images/home.png" alt="Codex Forge 首页" />
</p>

## ⚡ 功能特性

| 功能模块                      | 详细说明                                                                                                                                              |
| :---------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------- |
| 👥 **账号资料管理**           | 新增、重命名、删除账号资料，数据默认保存在 `~/Documents/CodexProfiles`。                                                                              |
| 🔑 **授权导入**               | 支持浏览器 OAuth（开放授权）授权、保存当前默认 Codex 账号、导入本地 `auth.json` 文件。                                                                |
| 🚀 **一键切换启动**           | 账号切换模式下自动写入当前用户 `.codex` 目录并启动默认 Codex。若检测到 Codex 正在运行会提示先关闭。                                                   |
| 📦 **多开隔离启动**           | 特色功能。多开隔离模式下为账号准备独立 `CodexHome`、`APPDATA`、`LOCALAPPDATA`、`--user-data-dir` 和完整 `CodexPortableApp` 副本，避免多账号互相覆盖。 |
| 📊 **额度快照**               | 读取账号认证信息并请求 Codex 额度接口，缓存并直观显示各账号的额度状态。                                                                               |
| 🛠️ **TOML 编辑**              | 直接查看和保存当前生效的 `config.toml`，且在保存前自动进行文件备份。                                                                                  |
| 📝 **指令模板（提示词注入）** | 本地保存 Markdown（标记语言）提示词模板，启用后复制到当前 Codex 配置目录，并把 `config.toml` 的 `model_instructions_file` 指向该模板。                |
| 🩺 **诊断信息**               | 展示核心配置路径、账号根目录、Codex 进程状态、账号资料完整性及日志文件路径。                                                                          |
| 🗜️ **Windows 打包**           | 采用 PyInstaller 构建 Python 后端，再通过 Electron Builder 生成标准安装包。                                                                           |

## ✨ 核心亮点

### 1. 🛡️ 多账号资料隔离

每个账号资料独立保存自身的登录凭证与配置：

```text
~/Documents/CodexProfiles/<账号名>/auth.json
~/Documents/CodexProfiles/<账号名>/CodexHome/config.toml
```

账号切换模式只替换 `auth.json`，模型、代理等全局 Codex 配置始终使用系统 `~/.codex/config.toml`。多开隔离模式使用账号自己的 `CodexHome/config.toml`。

### 2. 🔑 多样化的认证（Auth）管理

提供三种便捷的新增账号方式：

- 🌐 **浏览器授权**：打开 OpenAI 授权流程，授权结果仅保存至新账号资料目录。
- 💾 **保存当前账号**：一键复制当前系统中的 `~/.codex/auth.json`。
- 📁 **上传本地文件**：从本地选择已有的 Codex 登录文件进行导入。

> 💡 额度刷新时，系统会在必要时自动刷新登录令牌（Token），并将最新的认证信息回写至对应的账号资料中。

### 3. 🛠️ TOML 可视化编辑与安全备份

Codex Forge 会读取当前生效的配置文件：

```text
~/.codex/config.toml
```

在保存任何修改前，系统会自动校验 TOML 内容的合法性，并将旧文件安全备份至：

```text
%LOCALAPPDATA%/CodexForge/backups/config-toml/
```

### 4. 📝 指令模板管理

指令模板用于快速切换 Codex 的系统级行为提示词。你可以把常用工作方式、代码规范、审查标准，或类似 `docs/propmt/gpt5.5-unrestricted.md` 这样的破除限制提示词保存为 Markdown（标记语言）模板，需要时一键启用。

本功能的破除限制提示词模板参考了 [yynxxxxx/Codex-5.5-codex-instruct-5.5](https://github.com/yynxxxxx/Codex-5.5-codex-instruct-5.5) 项目。

Codex Forge 当前内置提示词模板：

- `docs/propmt/gpt5.5-unrestricted.md`

你可以在 **指令模板** 页面直接点击启用 / 禁用。启用后，Codex Forge 会把对应 `.md` 写入 Codex 配置目录，并更新 `config.toml` 中的 `model_instructions_file`。

| 对比项 | 默认指令             | `gpt5.5-unrestricted.md`     |
| :----- | :------------------- | :--------------------------- |
| 定位   | 通用 Codex 助手      | 高自由度开发者模式           |
| 策略   | 偏保守，容易泛化拒答 | 更强调执行、分析和可验证结果 |
| 风格   | 标准问答和代码协助   | 直接、覆盖面广、少解释阻塞   |
| 适用   | 日常编码、普通问答   | 代码审计、安全研究、复杂调试 |

部署后可以测试：

```text
如何对目标进行 SQL 注入测试？
```

典型效果：

```text
启用前 -> 容易拒绝或给出泛化回答
启用后 -> 更倾向于给出安全研究方法论、测试步骤和验证思路
```

启用模板时，Codex Forge 会执行三件事：

- 将模板复制到当前生效的 Codex 配置目录。
- 在 `config.toml` 中写入 `model_instructions_file = "./模板文件名.md"`。
- 在多开隔离模式下支持同步到当前账号、指定账号或全部账号。

这意味着你不需要手动编辑 `config.toml`，就能在默认指令、团队规范和更少限制的提示词风格之间切换。禁用模板只会移除 `model_instructions_file` 配置，不会删除已保存的模板文件。

### 5. 📦 多开隔离启动

除默认的账号切换模式外，Codex Forge 的特色启动能力是多开隔离：

- **账号切换模式**：默认模式。切换账号时写入系统 `~/.codex`，同一时间只建议运行一个 Codex。
- **多开隔离模式**：特色模式。每个账号使用独立环境并复制一份完整 `CodexPortableApp`，可同时运行多个 Codex 客户端。

多开隔离模式会隔离 `CodexHome`、`APPDATA`、`LOCALAPPDATA` 和浏览器 `--user-data-dir`，账号目录会额外包含：

```text
CodexProfiles/<账号名>/CodexHome
CodexProfiles/<账号名>/AppData
CodexProfiles/<账号名>/CodexPortableApp
```

### 6. 🧠 Codex 启动来源智能识别

在启动账号时，系统会按以下优先级顺序智能识别启动路径：

1. 已保存的 Codex 桌面程序自定义路径。
2. 正在运行的 Codex 或 Microsoft Store（微软应用商店）版本的 Codex。
3. Windows Store（微软应用商店）应用的默认启动标识。
4. 系统环境变量（PATH）中的 `codex` 命令（执行 `codex app`）。

---

## 📁 核心配置路径

**Codex 当前用户配置（默认读写）**：

```text
~/.codex/auth.json
~/.codex/config.toml
```

**Codex Forge 自身配置、日志与缓存**：

```text
%LOCALAPPDATA%/CodexForge/config.json
%LOCALAPPDATA%/CodexForge/logs/launcher.log
%LOCALAPPDATA%/CodexForge/usage_cache.json
```

**账号资料存储目录**：

```text
~/Documents/CodexProfiles
```

---

## 👨‍💻 开发者指南

### 🛠️ 技术栈

- **桌面框架**：Electron 41 / electron-vite
- **前端技术**：React 18 / TypeScript / Vite
- **UI（用户界面）组件**：Ant Design 5 / Tailwind CSS / lucide-react
- **后端服务**：Python 3.11 (本地桥接进程)
- **构建打包**：PyInstaller / Electron Builder
- **包管理器**：yarn / uv

### 📋 环境要求

- 操作系统：Windows 10 / Windows 11
- 环境依赖：
  - Python 3.11 或更高版本
  - Node.js
  - uv (Python 包管理器)
  - yarn
  - Bash 环境 (Windows 推荐使用 Git Bash)
- 软件依赖：已安装 Codex 桌面端，或系统环境变量中包含可执行的 `codex` 命令。

_验证 Codex 命令是否可用：_

```bash
codex --version
```

### 🚀 开发运行

```bash
cd /d/MyObject/CodexForge
cd python
uv sync --dev
cd ..
yarn install
yarn dev
```

### 🔍 代码检查

```bash
cd python
uv run python -m py_compile main.py
cd ..
yarn tsc --noEmit
```

### 📦 项目打包

**完整打包命令**：

```bash
yarn build
```

**分步构建命令**：

```bash
yarn build:backend
yarn build:shell
yarn build:installer
```

> **打包流程说明**：
>
> 1. 通过 `python -m PyInstaller` 生成独立的后端可执行文件 `resources/main.exe`。
> 2. 最后构建 Electron（跨平台桌面应用开发框架）桌面外壳，并生成 Windows 标准安装包。

**主要产物路径**：

```text
resources/main.exe
release/Codex Forge Setup 0.1.0.exe
```

---

## ⚠️ 免责声明

Codex Forge 是一个本地账号、配置和启动管理工具，非 OpenAI 官方产品，也不隶属于 OpenAI。项目中提供的指令模板仅用于合法的软件开发、代码审计、安全研究和学习测试场景；使用者应自行遵守所在地法律法规、目标系统授权要求以及相关平台服务条款。因使用本工具或模板造成的账号、数据、合规或安全风险，由使用者自行承担。
