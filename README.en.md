<p align="center">
  <a href="README.md">简体中文</a> |
  <a href="README.en.md">English</a>
</p>

<p align="center">
  <img src="src/renderer/src/assets/codex-forge-logo.png" alt="Codex Forge Logo" width="150" />
</p>

<h1 align="center">Codex Forge</h1>

<p align="center">
  <b>Codex multi-account and multi-instance management · Auth management · Visual TOML / instruction workspace</b>
</p>

<p align="center">
  A local multi-account and multi-instance management tool for Codex on Windows. It brings multiple Codex login profiles, <code>auth.json</code>, <code>config.toml</code>, instruction templates, and usage snapshots into one desktop interface. You can switch accounts before launching Codex, or use isolated environments to run multiple Codex clients at the same time.
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

## Overview

**Codex Forge** is not a replacement for Codex. It is a local workspace for Codex accounts, multi-instance launches, and configuration. It turns common terminal-side operations into desktop app workflows:

- **Multiple accounts**: Manage multiple Codex account profiles in one place.
- **Flexible auth import**: Add accounts through browser OAuth, the current default account, or a local `auth.json` file.
- **Smooth switching**: Write the selected account to `~/.codex/auth.json` automatically.
- **Config isolation**: Account-switching mode always uses the system `~/.codex/config.toml`; isolated multi-instance mode uses each account's `CodexHome/config.toml`.
- **Visual editing**: View and edit the active `~/.codex/config.toml`.
- **Template management**: Save, enable, and disable custom Codex instruction templates.
- **Status monitoring**: View account health, running status, and usage snapshots.
- **Selectable launch modes**: Supports the stable account-switching mode and an isolated multi-instance mode for running multiple Codex clients at the same time.

> **Note**: Isolated multi-instance mode copies a full `CodexPortableApp` for each account, so disk usage grows with account count. This version does not repair session providers or restore the old experimental session/memory sync features.

## Software Preview

<p align="center">
  <img src="docs/images/home.png" alt="Codex Forge home page" />
</p>

## Features

| Module | Details |
| :--- | :--- |
| **Profile management** | Create, rename, and delete account profiles. Data is stored in `~/Documents/CodexProfiles` by default. |
| **Auth import** | Supports browser OAuth, saving the current default Codex account, and importing a local `auth.json` file. |
| **One-click switch and launch** | In account-switching mode, writes the selected account into the current user's `.codex` directory and launches the default Codex app. If Codex is already running, the app prompts you to close it first. |
| **Isolated multi-instance launch** | Featured capability. In multi-instance mode, prepares a per-account `CodexHome`, `APPDATA`, `LOCALAPPDATA`, `--user-data-dir`, and full `CodexPortableApp` copy to avoid accounts overwriting each other. |
| **Usage snapshots** | Reads account auth data, requests the Codex usage endpoint, and caches each account's usage state. |
| **TOML editor** | Opens and saves the active `config.toml`, with an automatic backup before saving. |
| **Instruction templates** | Manages Markdown instruction templates locally. Enabling a template writes it into the Codex config and updates `model_instructions_file`. |
| **Diagnostics** | Shows key config paths, profile root, Codex process state, profile integrity, and log path. |
| **Windows packaging** | Builds the Python backend with PyInstaller, then creates a standard Windows installer with Electron Builder. |

## Highlights

### 1. Isolated Account Profiles

Each account profile stores its own login credentials and config:

```text
~/Documents/CodexProfiles/<profile-name>/auth.json
~/Documents/CodexProfiles/<profile-name>/CodexHome/config.toml
```

Account-switching mode only replaces `auth.json`; global Codex settings such as model and proxy always use the system `~/.codex/config.toml`. Isolated multi-instance mode uses each account's own `CodexHome/config.toml`.

### 2. Auth Management

There are three ways to add an account:

- **Browser OAuth**: Opens the OpenAI authorization flow and saves the result only to the new profile directory.
- **Save current account**: Copies the current system `~/.codex/auth.json`.
- **Upload local file**: Imports an existing Codex login file from disk.

> During usage refresh, Codex Forge refreshes login tokens when needed and writes the latest auth data back to the matching profile.

### 3. Visual TOML Editing with Backups

Codex Forge reads the active config file:

```text
~/.codex/config.toml
```

Before saving changes, it validates the TOML content and backs up the old file to:

```text
%LOCALAPPDATA%/CodexForge/backups/config-toml/
```

### 4. Instruction Template Management

Instruction templates are stored in the launcher's local directory. When a template is enabled, Codex Forge writes it into the current Codex config directory and updates `model_instructions_file` in `config.toml`.

### 5. Isolated Multi-instance Launch

In addition to the default account-switching mode, Codex Forge's featured launch capability is isolated multi-instance mode:

- **Account-switching mode**: The default mode. Switching accounts writes into the system `~/.codex`; one Codex instance is recommended.
- **Isolated multi-instance mode**: Featured mode. Each account uses an isolated environment and a full `CodexPortableApp` copy, allowing multiple Codex clients to run at once.

Isolated multi-instance mode separates `CodexHome`, `APPDATA`, `LOCALAPPDATA`, and the browser `--user-data-dir`. Each account directory also contains:

```text
CodexProfiles/<account>/CodexHome
CodexProfiles/<account>/AppData
CodexProfiles/<account>/CodexPortableApp
```

### 6. Smart Codex Launch Detection

When launching an account, Codex Forge resolves the launch source in this order:

1. Saved custom Codex desktop executable path.
2. Running Codex process or Microsoft Store version of Codex.
3. Windows Store app launch identifier.
4. `codex` command from `PATH`, executed as `codex app`.

---

## Core Paths

**Active Codex user config**:

```text
~/.codex/auth.json
~/.codex/config.toml
```

**Codex Forge config, logs, and cache**:

```text
%LOCALAPPDATA%/CodexForge/config.json
%LOCALAPPDATA%/CodexForge/logs/launcher.log
%LOCALAPPDATA%/CodexForge/usage_cache.json
```

**Account profile storage**:

```text
~/Documents/CodexProfiles
```

---

## Developer Guide

### Tech Stack

- **Desktop framework**: Electron 41 / electron-vite
- **Frontend**: React 18 / TypeScript / Vite
- **UI**: Ant Design 5 / Tailwind CSS / lucide-react
- **Backend**: Python 3.11 local bridge process
- **Build**: PyInstaller / Electron Builder
- **Package managers**: yarn / uv

### Requirements

- OS: Windows 10 / Windows 11
- Runtime dependencies:
  - Python 3.11 or later
  - Node.js
  - uv, the Python package manager
  - yarn
  - Bash environment, Git Bash is recommended on Windows
- Software dependency: Codex desktop app installed, or an executable `codex` command available in `PATH`.

*Check whether the Codex command is available:*

```bash
codex --version
```

### Development

```bash
cd /d/MyObject/CodexForge
cd python
uv sync --dev
cd ..
yarn install
yarn dev
```

### Checks

```bash
cd python
uv run python -m py_compile main.py
cd ..
yarn tsc --noEmit
```

### Packaging

**Full build:**

```bash
yarn build
```

**Step-by-step build:**

```bash
yarn build:backend
yarn build:shell
yarn build:installer
```

> **Build flow**:
> 1. Generate the standalone backend executable `resources/main.exe` with `python -m PyInstaller`.
> 2. Build the Electron desktop shell and generate the Windows installer.

**Main artifacts:**

```text
resources/main.exe
release/Codex Forge Setup 0.1.0.exe
```
