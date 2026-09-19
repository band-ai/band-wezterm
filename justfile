# Band WezTerm host — common local recipes
# https://github.com/casey/just

default:
    @just --list

# Install core + default-groups.dev from uv.lock
sync:
    uv sync

# Install core + all agent harness extras
sync-agents:
    uv sync --extra agents

# Open Control, or attach + raise if already running
start:
    uv run band-wezterm

# Same as start — find Control, activate it, raise WezTerm
attach:
    uv run band-wezterm

# Kill the Control window and open a fresh one
restart:
    uv run band-wezterm --restart

# Wire the Band WezTerm plugin into ~/.wezterm.lua (idempotent)
setup:
    uv run band-wezterm setup

# Unit tests
test:
    uv run pytest tests/unit -q

# WezTerm CLI live checks (needs wezterm on PATH)
test-wezterm:
    uv run pytest tests/integration/test_wezterm_cli_live.py -q

# Live platform Control PTY (needs BAND_API_KEY_USER in .env.test)
test-live:
    uv run pytest tests/integration/test_control_tab_pty.py -q
