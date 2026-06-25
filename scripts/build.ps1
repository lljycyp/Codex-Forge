$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

uv sync --dev

$PythonPrefix = (& .\.venv\Scripts\python.exe -c "import sys; print(sys.base_prefix)")
$TclPath = Join-Path $PythonPrefix "tcl\tcl8.6"
$TkPath = Join-Path $PythonPrefix "tcl\tk8.6"
if ((Test-Path $TclPath) -and (Test-Path $TkPath)) {
  $env:TCL_LIBRARY = $TclPath
  $env:TK_LIBRARY = $TkPath
}

uv run pyinstaller `
  --onefile `
  --windowed `
  --icon .\assets\app.ico `
  --add-data ".\assets\app.ico;assets" `
  --name CodexMultiLauncher `
  src\codex_multi_launcher\app.py

$OutputPath = ".\dist\CodexMultiLauncher.exe"
Write-Host "Built $OutputPath"
