# Band WezTerm host (INT-1496 discovery PoC)

Python terminal host that runs Band's Control surface **inside WezTerm** as a
permanent Control tab, with agent PTYs as visible Band-styled tabs.

## Requirements

- Python ≥ 3.12, [uv](https://github.com/astral-sh/uv)
- [WezTerm](https://wezterm.org/) on `PATH`
- Dev OAuth: set `BAND_OAUTH_CLIENT_ID` to the **jam** public client id (spike-only;
  request a dedicated `band-wezterm` client before dogfooding). Optional:
  `BAND_OAUTH_ISSUER` (default `https://auth.band.ai`), `BAND_BASE_URL`,
  `BAND_WS_URL`.

## Setup

```bash
uv sync          # installs default-groups.dev from uv.lock
# Point WezTerm at the Band Lua config (tab colors/status + focus):
#   echo 'dofile("/absolute/path/to/band-wezterm/wezterm/band.wezterm.lua")' >> ~/.wezterm.lua
uv run band-wezterm            # open Control, or attach + raise if already running
uv run band-wezterm --restart  # replace the Control window
```

Or with [just](https://github.com/casey/just): `just sync`, `just start` / `just attach`,
`just restart`, `just test` (`just --list` for all).

Re-running `band-wezterm` finds the existing Control tab, activates it, and
raises WezTerm — it does not spawn a second Control. `--restart` kills that
window first. Control opens in a normal (visible) WezTerm window; a separate
`band` workspace is avoided because WezTerm has no CLI to switch workspaces.

### Agent harnesses (Start agent)

Register only creates the platform identity. **Start** spawns
`python -m band_wezterm.agent` in a WezTerm tab with the matching
[band-sdk-python](https://github.com/band-ai/band-sdk-python) adapter.

```bash
# All four harnesses:
uv sync --extra agents

# Or one at a time:
uv sync --extra claude_sdk   # Claude CLI / claude-agent-sdk
uv sync --extra codex        # `codex login` or OPENAI_API_KEY / CODEX_API_KEY
uv sync --extra copilot_sdk  # Copilot CLI auth
uv sync --extra opencode     # OpenCode CLI auth
```

Host-side harness auth (Claude / Codex / Copilot / OpenCode CLI or API keys)
must already work on the machine — Start fails loud with an install hint when
the extra is missing.

**Re-register note:** managed agent API keys are one-time at registration. Agents
registered before this host persisted keys cannot be Started — register a new
agent from Control (the old platform identity can be deleted separately).

## Tests

```bash
uv sync
uv run pytest tests/unit -q
uv run pytest tests/integration/test_wezterm_cli_live.py -q   # needs wezterm on PATH

# Live platform (opt-in): copy .env.test.example → .env.test and set BAND_API_KEY_USER
# Same pattern as band-sdk-python / band-plugin-vsc — self-skips when the key is absent.
uv run pytest tests/integration/test_control_tab_pty.py -q
# Optional harness mention/reply (needs `--extra agents` + harness host auth):
uv run pytest tests/integration/test_live_harness_mention.py -q
```

## Security

Tokens and managed agent API keys live only in the OS keyring via `HostAuth` /
`TokenStore` / `ManagedAgentKeyStore`. OSC 1337 user-vars are allowlisted display
fields only — never tokens or message bodies. Spawn passes the agent key via a
short-lived `0600` key file (deleted after the pane reads it), never in argv/OSC.
