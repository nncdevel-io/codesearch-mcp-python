#!/usr/bin/env bash
# Provision toolchain for codesearch-mcp inside the devcontainer.
set -euo pipefail

echo "[post-create] installing system tools (ripgrep)..."
sudo apt-get update
sudo apt-get install -y --no-install-recommends ripgrep make

echo "[post-create] installing uv..."
if ! command -v uv >/dev/null 2>&1; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # shellcheck disable=SC1091
    source "$HOME/.local/bin/env" 2>/dev/null || true
    export PATH="$HOME/.local/bin:$PATH"
fi

echo "[post-create] installing markdownlint-cli2 and cspell (pinned for reproducibility)..."
sudo npm install -g markdownlint-cli2@0.22.1 cspell@10.0.0

echo "[post-create] syncing Python deps from uv.lock..."
uv sync --frozen

echo "[post-create] verifying toolchain..."
uv --version
git --version
rg --version | head -1
make --version | head -1
node --version

echo "[post-create] done. Run 'make verify' to execute the full quality gate."
