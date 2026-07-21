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

release_tag="v$(node -p "require('./package.json').version")"
head_commit="$(git rev-parse HEAD)"
tag_commit="$(git rev-list -n 1 "$release_tag")"

if [ "$head_commit" != "$tag_commit" ]; then
  echo "Release tag $release_tag does not point to current main commit"
  exit 1
fi

git checkout --detach "$release_tag"
export RELEASE_TAG="$release_tag"

npm config set registry https://registry.npmmirror.com
command -v yarn >/dev/null 2>&1 || npm install -g yarn
yarn config set registry https://registry.npmmirror.com

if ! command -v uv >/dev/null 2>&1; then
  powershell -WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
fi

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
yarn install --frozen-lockfile --network-timeout 600000
yarn build

export GITEE_UPLOAD_MAX_TIME=7200

gitee_status=0
github_status=0

node scripts/publish_gitee_release.js || gitee_status=$?
node scripts/publish_github_release.js || github_status=$?

if [ "$gitee_status" -ne 0 ] || [ "$github_status" -ne 0 ]; then
  echo "Release publishing failed: Gitee=$gitee_status GitHub=$github_status"
  exit 1
fi
