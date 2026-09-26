#!/usr/bin/env bash
# Idempotent repository bootstrap for the Mirza Bot Cloud Agent environment.
# Installs Python dependencies with uv and generates a local dev .env if absent.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# uv is baked into the base snapshot; reinstall if a fresh base ever lacks it.
if ! command -v uv >/dev/null 2>&1; then
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
export PATH="$HOME/.local/bin:$PATH"

# The gateway needs a repo-root .env (PROJECT_NAME must be space-free — it is the
# MongoDB database name). Seed it from the template without clobbering local edits.
if [ ! -f .env ]; then
  cp .cursor/dev.env.example .env
  echo "install.sh: created .env from .cursor/dev.env.example"
fi

# Install project + dev dependencies into app/.venv (fetches Python 3.13 via uv).
cd app
uv sync

echo "install.sh: dependencies synced"
