#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export UV_PROJECT_ENVIRONMENT="./python/.venv"

rm -rf build dist out release __pycache__
rm -f resources/main.exe
rm -f ./*.spec
find src python -type d \( -name "__pycache__" -o -name "*.egg-info" \) -prune -exec rm -rf {} + 2>/dev/null || true
uv run python ./python/clear_pyd.py

echo "Cleaned build artifacts."
