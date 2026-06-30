#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

export UV_PROJECT_ENVIRONMENT="./python/.venv"
export PY_BUILD="on"

cleanup() {
  uv run python ./python/clear_pyd.py || true
  export PY_BUILD="off"
}
trap cleanup EXIT

uv sync --dev
uv run python ./python/setup_pyd.py build_ext --inplace

mkdir -p resources
rm -f resources/main.exe

uv run pyinstaller \
  --onefile \
  --console \
  --name main \
  python/main.py \
  --noconfirm \
  --distpath resources \
  --workpath build/backend \
  --specpath build

echo "Built backend resources/main.exe"
