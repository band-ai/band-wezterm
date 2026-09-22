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

# Open a Band home view
start:
    uv run band

# Same as start
attach:
    uv run band

# Open a fresh Band home view
restart:
    uv run band --restart

# Install/update Band plugin snippet in active WezTerm config (idempotent)
setup:
    uv run band setup

# Unit tests
test:
    uv run pytest tests/unit -q

# WezTerm CLI live checks (needs wezterm on PATH)
test-wezterm:
    uv run pytest tests/integration/test_wezterm_cli_live.py tests/integration/test_plugin_setup_live.py -q

# Live platform Band-view PTY (needs BAND_API_KEY_USER in .env.test)
test-live:
    uv run pytest tests/integration/test_control_tab_pty.py -q

# Refresh README Band-view SVGs (no WezTerm or platform required)
screenshots:
    uv run python docs/capture_screenshots.py
