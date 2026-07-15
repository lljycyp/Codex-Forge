#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

(cd "$PROJECT_ROOT/python" && uv sync --dev)

mkdir -p resources
rm -f resources/main.exe

(cd "$PROJECT_ROOT/python" && uv run python -m PyInstaller \
  --onefile \
  --console \
  --name main \
  --add-data ../docs/propmt/gpt5.5-unrestricted.md:docs/propmt \
  --add-data ../docs/propmt/gpt-5.6-sol-unrestricted.md:docs/propmt \
  main.py \
  --noconfirm \
  --distpath ../resources \
  --workpath ../build/backend \
  --specpath ../build)

echo "Built backend resources/main.exe"
