# CodexMultiLauncher

CodexMultiLauncher 是一个 Windows 桌面工具，用于用独立环境启动多个 Codex 桌面端账号。

每个账号会隔离：

- `APPDATA`
- `LOCALAPPDATA`
- `CODEX_HOME`
- 每个账号目录下的 `CodexPortableApp`
- Codex Web 容器的 `--user-data-dir`

启动器会对配置文件做原子写入和最近两次备份，并提供“诊断”入口检查路径、权限、账号目录和程序副本状态。

可选开启“实验性同步会话”，让多个账号共享 Codex 侧栏会话列表、会话文件和附件；也可单独开启“实验性同步记忆”合并 Codex 记忆。登录信息、完整配置、插件和浏览器数据仍保持隔离。

## 环境要求

- Windows 10 / Windows 11
- Python 3.11 或更高版本
- uv
- Codex 桌面端 `Codex.exe`

检查 uv：

```powershell
uv --version
```

## 初始化环境

```powershell
cd D:\MyObject\CodexMultiLauncher
uv sync
```

安装开发和打包依赖：

```powershell
uv sync --dev
```

## 运行源码

```powershell
uv run codex-multi-launcher
```

也可以使用脚本：

```powershell
.\scripts\run.ps1
```

## 语法检查

```powershell
uv run python -m py_compile .\src\codex_multi_launcher\app.py
```

## 打包 exe

```powershell
.\scripts\build.ps1
```

打包完成后会生成：

```text
dist\CodexMultiLauncher.exe
```

## 清理构建产物

```powershell
.\scripts\clean.ps1
```

## 文档

- [使用说明](docs/使用说明.md)
- [开发打包说明](docs/开发打包说明.md)

## 说明

根目录不需要保存 `CodexPortableApp`。启动器会自动识别微软商店版 Codex，并在每个账号目录下创建独立的 `CodexPortableApp` 副本。
