$ErrorActionPreference = "Stop"

Set-Location (Split-Path -Parent $PSScriptRoot)
uv run codex-multi-launcher

