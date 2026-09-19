#!/usr/bin/env bash

set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

uv tool install --force --reinstall "$SCRIPT_DIR"
band-wezterm setup

printf '%s\n' "Band WezTerm is installed. Run: band-wezterm"
