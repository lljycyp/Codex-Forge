<p align="center">
  <a href="README.md">简体中文</a> |
  <a href="README.en.md">English</a>
</p>

<p align="center">
  <img src="src/renderer/src/assets/codex-forge-logo.png" alt="Codex Forge Logo" width="150" />
</p>

<h1 align="center">Codex Forge</h1>

<p align="center">
  <b>Codex account switching · Auth management · Visual TOML / instruction workspace</b>
</p>

<p align="center">
  A local management tool for Codex on Windows. It brings multiple Codex login profiles, <code>auth.json</code>, <code>config.toml</code>, instruction templates, and usage snapshots into one desktop interface. When switching accounts, it writes the selected profile into the current user's <code>.codex</code> directory and launches Codex.
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

**Codex Forge** is not a replacement for Codex. It is a local workspace for Codex accounts and configuration. It turns common terminal-side operations into desktop app workflows:

- **Multiple accounts**: Manage multiple Codex account profiles in one place.
- **Flexible auth import**: Add accounts through browser OAuth, the current default account, or a local `auth.json` file.
- **Smooth switching**: Write the selected account to `~/.codex/auth.json` automatically.
- **Config isolation**: Share the system `config.toml` across accounts, or keep a separate config per account.
- **Visual editing**: View and edit the active `~/.codex/config.toml`.
- **Template management**: Save, enable, and disable custom Codex instruction templates.
- **Status monitoring**: View account health, running status, and usage snapshots.
- **Smart launch**: Detect and launch the installed Codex desktop app or the `codex app` command.

> **Note**: The current version does not copy the Codex program directory, repair session providers, or run multiple accounts concurrently.

## Features

| Module | Details |
| :--- | :--- |
| **Profile management** | Create, rename, and delete account profiles. Data is stored in `~/Documents/CodexProfiles` by default. |
| **Auth import** | Supports browser OAuth, saving the current default Codex account, and importing a local `auth.json` file. |
| **One-click switch and launch** | Writes the selected account into the current user's `.codex` directory and launches the default Codex app. If Codex is already running, the app prompts you to close it first. |
| **Usage snapshots** | Reads account auth data, requests the Codex usage endpoint, and caches each account's usage state. |
| **TOML editor** | Opens and saves the active `config.toml`, with an automatic backup before saving. |
| **Instruction templates** | Manages Markdown instruction templates locally. Enabling a template writes it into the Codex config and updates `model_instructions_file`. |
| **Diagnostics** | Shows key config paths, profile root, Codex process state, profile integrity, and log path. |
| **Windows packaging** | Builds the Python backend with Cython and PyInstaller, then creates a standard Windows installer with Electron Builder. |

## Highlights

### 1. Isolated Account Profiles

Each account profile stores its own login credentials and config:

```text
~/Documents/CodexProfiles/<profile-name>/auth.json
~/Documents/CodexProfiles/<profile-name>/config.toml
```

When "share system config.toml" is enabled, switching accounts only replaces `auth.json`; global Codex settings such as model and proxy continue to use the active system config.

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

### 5. Smart Codex Launch Detection

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
- **Build**: Cython / PyInstaller / Electron Builder
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
export UV_PROJECT_ENVIRONMENT="./python/.venv"
uv sync --dev
yarn install
yarn dev
```

### Checks

```bash
export UV_PROJECT_ENVIRONMENT="./python/.venv"
uv run python -m py_compile ./python/main.py
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
> 1. Compile protected Python core modules with Cython.
> 2. Generate the standalone backend executable `resources/main.exe` with `python -m PyInstaller`.
> 3. Build the Electron desktop shell and generate the Windows installer.

**Main artifacts:**

```text
resources/main.exe
release/Codex Forge Setup 0.1.0.exe
```
