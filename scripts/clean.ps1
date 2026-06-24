$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Remove-Item .\build -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .\dist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .\*.spec -Force -ErrorAction SilentlyContinue
Remove-Item .\__pycache__ -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem .\src -Directory -Recurse -Filter __pycache__ -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem .\src -Directory -Recurse -Filter *.egg-info -ErrorAction SilentlyContinue |
  Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

Write-Host "Cleaned build artifacts."
