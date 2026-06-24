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

$OutputPath = ".\CodexMultiLauncher.exe"
$FallbackPath = ".\CodexMultiLauncher.new.exe"

try {
  Copy-Item .\dist\CodexMultiLauncher.exe $OutputPath -Force
  Write-Host "Built $OutputPath"
} catch {
  Copy-Item .\dist\CodexMultiLauncher.exe $FallbackPath -Force
  Write-Warning "Could not overwrite $OutputPath. It may be running. Built $FallbackPath instead."
}
