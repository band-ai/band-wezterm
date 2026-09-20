#!/usr/bin/env bash

set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPOSITORY="https://github.com/band-ai/band-wezterm"
readonly REMOTE_PACKAGE="band-wezterm[agents] @ git+${REPOSITORY}.git@main"

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if grep -qx 'name = "band-wezterm"' "$SCRIPT_DIR/pyproject.toml" 2>/dev/null; then
  PACKAGE="$SCRIPT_DIR[agents]"
else
  PACKAGE="$REMOTE_PACKAGE"
fi

uv tool install --force --reinstall "$PACKAGE"
band-wezterm setup

printf '%s\n' "Band WezTerm is installed. Run: band-wezterm"
