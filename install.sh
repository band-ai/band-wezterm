#!/usr/bin/env bash

set -euo pipefail

readonly SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly REPOSITORY="https://github.com/band-ai/band-wezterm"

usage() {
  printf '%s\n' "Usage: install.sh [--release|--main|--source]"
}

is_local_project() {
  grep -qx 'name = "band-wezterm"' "$SCRIPT_DIR/pyproject.toml" 2>/dev/null
}

latest_release_tag() {
  local refs tag
  if ! refs="$(git ls-remote --refs --tags "${REPOSITORY}.git" 'v*')"; then
    printf '%s\n' "Git access is required to find the latest Band WezTerm release." >&2
    return 1
  fi
  tag="$(printf '%s\n' "$refs" | awk -F/ '/refs\/tags\/v[0-9][0-9]*\.[0-9][0-9]*\.[0-9][0-9]*$/ {print $3}' | LC_ALL=C sort -t. -k1.2,1n -k2,2n -k3,3n | tail -n 1)"
  case "$tag" in
    v[0-9]*) printf '%s\n' "$tag" ;;
    *)
      printf '%s\n' "Could not determine the latest Band WezTerm release." >&2
      return 1
      ;;
  esac
}

install_channel="${BAND_WEZTERM_CHANNEL:-}"
case "${1:-}" in
  "") ;;
  --release) install_channel="release" ;;
  --main) install_channel="main" ;;
  --source) install_channel="source" ;;
  *)
    usage >&2
    exit 2
    ;;
esac

if [[ -z "$install_channel" ]]; then
  if is_local_project; then
    install_channel="source"
  else
    install_channel="release"
  fi
fi

if ! command -v uv >/dev/null 2>&1; then
  printf '%s\n' "uv is required: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
fi

if [[ "$install_channel" != "source" ]] && ! command -v git >/dev/null 2>&1; then
  printf '%s\n' "Git is required to install Band WezTerm from a release or main." >&2
  exit 1
fi

case "$install_channel" in
  source)
    if ! is_local_project; then
      printf '%s\n' "--source requires a Band WezTerm checkout." >&2
      exit 2
    fi
    package="$SCRIPT_DIR[agents]"
    printf '%s\n' "Installing Band WezTerm from this checkout."
    ;;
  main)
    package="band-wezterm[agents] @ git+${REPOSITORY}.git@main"
    printf '%s\n' "Installing Band WezTerm from main."
    ;;
  release)
    release_tag="$(latest_release_tag)"
    package="band-wezterm[agents] @ git+${REPOSITORY}.git@${release_tag}"
    printf '%s\n' "Installing Band WezTerm release ${release_tag}."
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac

uv tool install --force --reinstall "$package"
band-wezterm setup

printf '%s\n' "Band WezTerm is installed. Run: band-wezterm"
