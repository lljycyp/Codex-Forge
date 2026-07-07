#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export PY_BUILD="on"

cleanup() {
  (cd "$PROJECT_ROOT/python" && uv run python clear_pyd.py) || true
  export PY_BUILD="off"
}
trap cleanup EXIT

(cd "$PROJECT_ROOT/python" && uv sync --dev)
(cd "$PROJECT_ROOT/python" && uv run python setup_pyd.py build_ext --inplace)

mkdir -p resources
rm -f resources/main.exe

(cd "$PROJECT_ROOT/python" && uv run python -m PyInstaller \
  --onefile \
  --console \
  --name main \
  main.py \
  --noconfirm \
  --distpath ../resources \
  --workpath ../build/backend \
  --specpath ../build)

echo "Built backend resources/main.exe"
