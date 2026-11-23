[CmdletBinding()]
param(
  [switch]$Apply,
  [string[]]$BackupRoots = @()
)

$ErrorActionPreference = "Stop"

function Resolve-SafePath([string]$Path) {
  $resolved = [System.IO.Path]::GetFullPath($Path)
  $root = [System.IO.Path]::GetPathRoot($resolved)
  if ($resolved -eq $root) {
    throw "拒绝使用磁盘根目录作为迁移目标: $resolved"
  }
  return $resolved.TrimEnd('\')
}

function Move-Recorded([string]$Source, [string]$Destination, [System.Collections.ArrayList]$Moves) {
  if (!(Test-Path -LiteralPath $Source)) {
    return
  }
  if (Test-Path -LiteralPath $Destination) {
    throw "迁移目标已存在: $Destination"
  }
  Write-Host "移动: $Source -> $Destination"
  $parent = Split-Path -Parent $Destination
  New-Item -ItemType Directory -Path $parent -Force | Out-Null
  Move-Item -LiteralPath $Source -Destination $Destination
  if (!(Test-Path -LiteralPath $Destination)) {
    throw "迁移后目标不存在: $Destination"
  }
  [void]$Moves.Add([pscustomobject]@{ Source = $Source; Destination = $Destination })
}

$workspaceRoot = Resolve-SafePath (Join-Path $PSScriptRoot "..")
$localSource = Resolve-SafePath (Join-Path $env:LOCALAPPDATA "ChatGPTForge")
$localTarget = Resolve-SafePath (Join-Path $env:LOCALAPPDATA "CodexForge")
$roamingSource = Resolve-SafePath (Join-Path $env:APPDATA "chatgpt-forge-desktop")
$roamingTarget = Resolve-SafePath (Join-Path $env:APPDATA "codex-forge-desktop")
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = Resolve-SafePath (Join-Path $env:LOCALAPPDATA "CodexForgeMigrationBackups\$timestamp")

$mappings = @(
  [pscustomobject]@{ Source = $localSource; Target = $localTarget; BackupName = "previous-local-CodexForge" },
  [pscustomobject]@{ Source = $roamingSource; Target = $roamingTarget; BackupName = "previous-roaming-codex-forge-desktop" }
)
$running = Get-CimInstance Win32_Process | Where-Object {
  $_.Name -in @("Codex Forge.exe", "ChatGPT Forge.exe") -or
  ($_.CommandLine -and (
    $_.CommandLine.Contains("python\bridge\commands.py") -or
    $_.CommandLine.Contains("launcherBackend") -or
    $_.CommandLine.Contains("out\main\index.js")
  ))
}
if ($running) {
  $running | Select-Object ProcessId, Name, CommandLine | Format-Table -AutoSize
  if ($Apply) {
    throw "检测到 Codex Forge 开发进程或旧版进程，请先退出后再迁移。"
  }
  Write-Warning "Dry Run 检测到运行中的相关进程；正式迁移前必须先退出。"
}

$plan = foreach ($mapping in $mappings) {
  [pscustomobject]@{
    SourceExists = Test-Path -LiteralPath $mapping.Source
    Source = $mapping.Source
    TargetExists = Test-Path -LiteralPath $mapping.Target
    Target = $mapping.Target
  }
}
$plan | Format-Table -AutoSize

if (!$Apply) {
  Write-Host "Dry Run 完成。确认路径无误后使用 -Apply 执行迁移。"
  exit 0
}

if (!(Test-Path -LiteralPath $localSource)) {
  if (Test-Path -LiteralPath (Join-Path $localTarget "codex_forge.db")) {
    Write-Host "Codex Forge 数据已迁移，无需重复执行。"
    exit 0
  }
  throw "找不到当前应用数据目录: $localSource"
}

$moves = [System.Collections.ArrayList]::new()
New-Item -ItemType Directory -Path $backupRoot -Force | Out-Null

try {
  foreach ($mapping in $mappings) {
    if (Test-Path -LiteralPath $mapping.Target) {
      Move-Recorded $mapping.Target (Join-Path $backupRoot $mapping.BackupName) $moves
    }
    Move-Recorded $mapping.Source $mapping.Target $moves
  }

  $oldDatabase = Join-Path $localTarget "chatgpt_forge.db"
  $newDatabase = Join-Path $localTarget "codex_forge.db"
  if (!(Test-Path -LiteralPath $oldDatabase)) {
    throw "迁移后的旧数据库不存在: $oldDatabase"
  }
  Copy-Item -LiteralPath $oldDatabase -Destination (Join-Path $backupRoot "chatgpt_forge.db.before-content-migration")
  Move-Recorded $oldDatabase $newDatabase $moves

  $localStorage = Join-Path $roamingTarget "Local Storage"
  if (Test-Path -LiteralPath $localStorage) {
    Copy-Item -LiteralPath $localStorage -Destination (Join-Path $backupRoot "electron-local-storage-before-migration") -Recurse
  }

  $python = Join-Path $workspaceRoot "python\.venv\Scripts\python.exe"
  if (!(Test-Path -LiteralPath $python)) {
    throw "找不到项目 Python 运行时: $python"
  }
  $pythonArgs = @((Join-Path $workspaceRoot "scripts\migrate_codex_forge_data.py"), "--database", $newDatabase)
  foreach ($root in $BackupRoots) {
    $pythonArgs += @("--backup-root", (Resolve-SafePath $root))
  }
  & $python @pythonArgs
  if ($LASTEXITCODE -ne 0) {
    throw "数据库或账号备份内容迁移失败。"
  }

  $electron = Join-Path $workspaceRoot "node_modules\.bin\electron.cmd"
  $renderer = Join-Path $workspaceRoot "out\renderer\index.html"
  if (!(Test-Path -LiteralPath $electron) -or !(Test-Path -LiteralPath $renderer)) {
    throw "缺少 Electron 或已构建渲染页面，请先执行 yarn build:shell。"
  }
  & $electron (Join-Path $workspaceRoot "scripts\migrate_electron_storage.cjs") $roamingTarget
  if ($LASTEXITCODE -ne 0) {
    throw "Electron Local Storage 迁移失败。"
  }

  $manifest = [ordered]@{
    completedAt = (Get-Date).ToString("o")
    backupRoot = $backupRoot
    databaseSha256 = (Get-FileHash -LiteralPath $newDatabase -Algorithm SHA256).Hash
    mappings = $plan
    moves = $moves
  }
  $manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $backupRoot "migration-manifest.json") -Encoding utf8
  Write-Host "迁移完成，回滚资料保存在: $backupRoot"
} catch {
  Write-Warning "迁移失败，开始恢复已移动的目录。错误: $($_.Exception.Message)"
  for ($index = $moves.Count - 1; $index -ge 0; $index--) {
    $move = $moves[$index]
    if ((Test-Path -LiteralPath $move.Destination) -and !(Test-Path -LiteralPath $move.Source)) {
      Move-Item -LiteralPath $move.Destination -Destination $move.Source
    }
  }
  $databaseBackup = Join-Path $backupRoot "chatgpt_forge.db.before-content-migration"
  $restoredDatabase = Join-Path $localSource "chatgpt_forge.db"
  if ((Test-Path -LiteralPath $databaseBackup) -and (Test-Path -LiteralPath $restoredDatabase)) {
    [System.IO.File]::Copy($databaseBackup, $restoredDatabase, $true)
  }
  $storageBackup = Join-Path $backupRoot "electron-local-storage-before-migration"
  $restoredStorage = Join-Path $roamingSource "Local Storage"
  if (Test-Path -LiteralPath $storageBackup) {
    if (Test-Path -LiteralPath $restoredStorage) {
      [System.IO.Directory]::Delete($restoredStorage, $true)
    }
    Copy-Item -LiteralPath $storageBackup -Destination $restoredStorage -Recurse
  }
  throw
}
