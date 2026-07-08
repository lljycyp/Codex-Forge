#!/usr/bin/env bash
set -euo pipefail

repo=/d/gitee_go/codex-forge

if [ -e "$repo" ] && [ ! -d "$repo/.git" ]; then
  rm -rf "$repo"
fi

if [ ! -d "$repo/.git" ]; then
  git clone https://gitee.com/llj20010218/codex-forge.git "$repo"
fi

cd "$repo"
git remote set-url origin https://gitee.com/llj20010218/codex-forge.git
git fetch --tags origin
git checkout main
git pull --ff-only origin main

npm config set registry https://registry.npmmirror.com
command -v yarn >/dev/null 2>&1 || npm install -g yarn
yarn config set registry https://registry.npmmirror.com

if ! command -v uv >/dev/null 2>&1; then
  powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
fi

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
yarn install --frozen-lockfile --network-timeout 600000
yarn build

export GITEE_TOKEN="${G_TOKEN}"
if [ -z "$GITEE_TOKEN" ]; then
  echo "G_TOKEN is required in Gitee Go variables"
  exit 1
fi

export GITEE_UPLOAD_MAX_TIME=7200
node scripts/publish_gitee_release.js
