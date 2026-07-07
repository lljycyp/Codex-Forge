#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# 清理上次失败留下的半成品目录，避免 electron-builder 复用缺少 electron.exe 的残留输出。
rm -rf release/win-unpacked

# 清理当前 Electron 版本的缓存压缩包，避免上次中断下载留下的坏包导致解压失败。
ELECTRON_VERSION="$(node -p "require('./package.json').devDependencies.electron.replace(/^[^0-9]*/, '')")"
if [[ -n "${LOCALAPPDATA:-}" ]] && command -v cygpath >/dev/null 2>&1; then
  ELECTRON_CACHE_DIR="$(cygpath -u "$LOCALAPPDATA")/electron/Cache"
  rm -f "$ELECTRON_CACHE_DIR/electron-v$ELECTRON_VERSION-win32-x64.zip"
  rm -f "$ELECTRON_CACHE_DIR"/*/"electron-v$ELECTRON_VERSION-win32-x64.zip" 2>/dev/null || true
fi

electron-builder --win --publish never
node scripts/write_release_notes.js
