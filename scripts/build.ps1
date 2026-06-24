$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

uv sync --dev

uv run pyinstaller `
  --onefile `
  --windowed `
  --icon .\assets\app.ico `
  --add-data ".\assets\app.ico;assets" `
  --name CodexMultiLauncher `
  src\codex_multi_launcher\app.py

$OutputPath = ".\dist\CodexMultiLauncher.exe"
Write-Host "Built $OutputPath"
