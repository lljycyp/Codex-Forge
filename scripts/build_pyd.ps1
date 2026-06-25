$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

$env:PY_BUILD = "on"

function Invoke-Checked {
  param(
    [Parameter(Mandatory = $true)]
    [scriptblock]$Command,
    [Parameter(Mandatory = $true)]
    [string]$Message
  )

  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw $Message
  }
}

try {
  Invoke-Checked { uv sync --dev } "依赖同步失败。"

  Invoke-Checked { uv run setup_pyd.py build_ext --inplace } "pyd 编译失败。"

  $PythonPrefix = (& .\.venv\Scripts\python.exe -c "import sys; print(sys.base_prefix)")
  $TclPath = Join-Path $PythonPrefix "tcl\tcl8.6"
  $TkPath = Join-Path $PythonPrefix "tcl\tk8.6"
  if ((Test-Path $TclPath) -and (Test-Path $TkPath)) {
    $env:TCL_LIBRARY = $TclPath
    $env:TK_LIBRARY = $TkPath
  }

  $IconPath = Join-Path $ProjectRoot "assets\app.ico"
  $IconData = "$IconPath;assets"

  Invoke-Checked {
    uv run pyinstaller `
    --onefile `
    --windowed `
    --icon $IconPath `
    --add-data $IconData `
    --name CodexMultiLauncher `
    src\codex_multi_launcher\main.py `
    --noconfirm `
    --specpath build
  } "PyInstaller 打包失败；如果提示拒绝访问，请先关闭正在运行的 CodexMultiLauncher.exe。"

  $OutputPath = ".\dist\CodexMultiLauncher.exe"
  Write-Host "Built protected $OutputPath"
}
finally {
  & uv run clear_pyd.py
  $env:PY_BUILD = "off"
}
