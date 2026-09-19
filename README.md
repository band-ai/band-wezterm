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
# Point WezTerm at the Band Lua config (tab colors/status):
#   echo 'dofile("/absolute/path/to/band-wezterm/wezterm/band.wezterm.lua")' >> ~/.wezterm.lua
uv run band-wezterm
```

## Tests

```bash
uv sync
uv run pytest tests/unit -q
uv run pytest tests/integration/test_wezterm_cli_live.py -q   # needs wezterm on PATH

# Live platform (opt-in): copy .env.test.example → .env.test and set BAND_API_KEY_USER
# Same pattern as band-sdk-python / band-plugin-vsc — self-skips when the key is absent.
uv run pytest tests/integration/test_control_tab_pty.py -q
```

## Security

Tokens live only in the OS keyring via `HostAuth` / `TokenStore`. OSC 1337
user-vars are allowlisted display fields only — never tokens or message bodies.
