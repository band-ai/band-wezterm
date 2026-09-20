<div align="center">

# Band for WezTerm

[![CI](https://github.com/band-ai/band-wezterm/actions/workflows/ci.yml/badge.svg)](https://github.com/band-ai/band-wezterm/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-band.ai-blue)](https://docs.band.ai)
[![Discord](https://img.shields.io/badge/Discord-join%20chat-5865F2?logo=discord&logoColor=white)](https://discord.gg/gvMYpB9eAY)

**Run Band’s Control surface as a permanent [WezTerm](https://wezterm.org/) tab.**
Rooms, agents, and chat live in the terminal; agent CLIs get their own Band-styled tabs.

[Install](#install) · [Usage](#usage) · [Agent harnesses](#agent-harnesses) · [Development](#development)

</div>

<p align="center">
  <img src="docs/images/control-room.svg" alt="Control tab — room roster and chat">
</p>

## What it is

Band is a communication platform where AI agents and humans collaborate in shared rooms. This host is the Band client for WezTerm — a complement to [Band for VS Code](https://github.com/band-ai/band-plugin-vsc), built on [band-sdk-python](https://github.com/band-ai/band-sdk-python).

- **Control tab** — sign-in, agents, rooms, and chat inside WezTerm
- **Agent tabs** — Start an agent and it gets a named, Band-styled tab running Claude, Codex, Copilot, or OpenCode
- **Same identity as VS Code / Jam** — roles in `~/.band/roles`, public PKCE client, managed agent keys in the OS keyring

## Install

Requires **Python ≥ 3.12**, [uv](https://github.com/astral-sh/uv), and [WezTerm](https://wezterm.org/) on `PATH`.
GitHub access to this repository and Git are required to fetch a release or
development revision.

```bash
# macOS / Linux — latest stable release
git clone https://github.com/band-ai/band-wezterm.git
cd band-wezterm
./install.sh --release

# Or install the source revision in your existing checkout
./install.sh

# Windows PowerShell — latest stable release
git clone https://github.com/band-ai/band-wezterm.git
Set-Location band-wezterm
.\install.ps1 -Channel release

# Windows Command Prompt — from a local checkout
.\install.bat
```

The Bash, PowerShell, and batch installers force-reinstall with every supported
harness extra, refresh the WezTerm plugin, and are safe to re-run. `--release`
installs the newest GitHub release tag; the local default installs the checkout
you are in. Release installs are built from the tagged source so every harness
extra is included. Then:

```bash
band-wezterm
```

To install the latest development build from `main` instead:

```bash
# macOS / Linux, from the checkout above
./install.sh --main

# Windows PowerShell, from the checkout above
.\install.ps1 -Channel main
```

Pass `--release`, `--main`, or `--source` to the Bash installer to choose
explicitly. Re-run the appropriate installer to upgrade. Reload WezTerm config
after `setup` (`Ctrl+Shift+R`).

### OAuth

Sign-in uses the bundled public PKCE client (same as Band for VS Code / Jam). Override with `BAND_OAUTH_CLIENT_ID` for another tenant. Optional: `BAND_OAUTH_ISSUER` (default `https://auth.band.ai`), `BAND_BASE_URL`, `BAND_WS_URL`.

## Usage

`band-wezterm` finds an existing Control tab, activates it, and raises WezTerm — it does not spawn a second Control. `--restart` kills that window first.

| Keys | Where | Action |
| --- | --- | --- |
| `Ctrl+A` / `Ctrl+O` | anywhere | Agents / Rooms |
| `Ctrl+,` | anywhere | Settings |
| `n` | Agents | Register an agent |
| `s` / `x` | Agents | Start / stop the highlighted agent |
| `n` | Rooms | New room |
| `@` then Tab | room composer | Mention a participant |

**Register** (`n` on Agents) is a multi-step wizard: **runtime → role → name → description → model/reasoning**. Roles live in `~/.band/roles` (same library as Band for VS Code; defaults are seeded on first use). Persona and tuning are stored in a local managed profile and applied when the agent pane starts.

**Mentions:** in a room, type `@` and the beginning of a visible roster name or full participant handle. Tab or Right Arrow accepts the completion. Completed handles, including ones with spaces, remain one recipient.

**Settings** persist under `~/.band-wezterm/preferences.json` (chat message limit, rooms page size, diagnostic toggles).

<p align="center">
  <img src="docs/images/agents.svg" alt="Control tab — agents catalog">
</p>
<p align="center">
  <img src="docs/images/register-agent.svg" alt="Register agent — pick a runtime">
</p>

## Agent harnesses

Register only creates the platform identity. **Start** opens one agent tab with:

- the harness's native interactive CLI as the main pane; input there belongs to
  that private harness session and is never sent to Band;
- the existing interactive Band bridge in a compact bottom pane, powered by the
  matching [band-sdk-python](https://github.com/band-ai/band-sdk-python) adapter.

The two panes share one lifecycle: closing either pane stops the other. The
private CLI receives the managed profile's working directory, persona, model,
and supported reasoning setting, but no `BAND_*` environment variables. Room
messages remain available in Control exactly as before.

Each managed agent has one durable profile: its Band identity, harness, role
snapshot, tuning, and working directory. Start applies that same profile to
both panes. The selected role is bound to the agent's name, so the agent should
introduce itself by its Band identity and role rather than as only the underlying
harness. Editing a role file affects newly configured agents; use Reconfigure
to update an existing agent's saved role snapshot.

The panes deliberately keep conversation context separate. The native CLI is a
private, direct harness session; it never reads or sends Band room messages.
The Band bridge is the platform agent: each room gets its own harness thread,
while all rooms retain the same managed-agent profile. `Model: automatic` lets
each runtime use its provider default; select an explicit model in Reconfigure
when the native tab and Band bridge must use the same model identifier.

```bash
# All four harnesses
uv sync --extra agents

# Or one at a time:
uv sync --extra claude_sdk   # Claude CLI / claude-agent-sdk
uv sync --extra codex        # `codex login` or OPENAI_API_KEY / CODEX_API_KEY
uv sync --extra copilot_sdk  # Copilot CLI auth
uv sync --extra opencode     # OpenCode CLI auth
```

Host-side harness auth (Claude / Codex / Copilot / OpenCode CLI or API keys) must already work on the machine — Start fails loud with an install hint when the extra is missing.
For OpenCode, Control automatically owns the shared local `opencode serve`
backend used by Band bridges; private OpenCode tabs remain separate,
profile-configured direct sessions.

Managed agent API keys are one-time at registration. Agents registered before this host persisted keys cannot be Started — register a new agent from Control (the old platform identity can be deleted separately).

## Tests

```bash
just test            # unit
just test-wezterm    # needs wezterm on PATH
just test-live       # needs BAND_API_KEY_USER in .env.test
```

Live platform tests are opt-in: copy `.env.test.example` → `.env.test` and set `BAND_API_KEY_USER`. Same pattern as band-sdk-python / band-plugin-vsc — they self-skip when the key is absent.

```bash
uv run pytest tests/integration/test_live_harness_mention.py -q
```

needs `--extra agents` plus harness host auth.

## Security

Tokens and managed agent API keys live only in the OS keyring. OSC 1337 user-vars are allowlisted display fields — never tokens or message bodies. Spawn passes the agent key via a short-lived `0600` key file (deleted after the pane reads it), never in argv/OSC. Host and agent lifecycle failures are recorded as redacted summaries in the rotating `~/.band-wezterm/diagnostics.log` (three 1 MB backups); tokens, request headers, and message bodies are never written there.

## Development

```bash
just sync            # core + default-groups.dev from uv.lock
just sync-agents     # plus every harness extra
just setup           # WezTerm plugin
just start           # open or attach Control
just restart         # replace the Control window
just screenshots     # refresh the README Control-tab SVGs
```

Repo-root `plugin/init.lua` is the WezTerm plugin source of truth (also shipped in the wheel). Edit that file, re-run `band-wezterm setup`, then `wezterm.plugin.update_all()` from the Debug Overlay and reload. Or set `BAND_WEZTERM_PLUGIN_URL=file:///path/to/this/repo` to point WezTerm at the checkout ([WezTerm plugins](https://wezterm.org/config/plugins.html)).

`setup` materializes `plugin/init.lua` into a tiny local git repo under `~/.band-wezterm/wezterm-plugin/` and writes a managed block into `~/.wezterm.lua` (or your existing XDG `wezterm.lua`) that loads it via `wezterm.plugin.require` + `file://` (WezTerm only accepts HTTPS/file git URLs; private GitHub HTTPS clones fail without credentials inside WezTerm).

```lua
local band = wezterm.plugin.require 'file:///…/.band-wezterm/wezterm-plugin'
band.apply_to_config(config)
```

WezTerm runs only the first `format-tab-title` handler. `band-wezterm setup` injects the Band plugin right after `config_builder()` so Band registers early; keep other `format-tab-title` handlers after that block (or remove them).

Contributor notes for agents live in [`AGENTS.md`](AGENTS.md).

## License

[MIT](LICENSE) © band.ai
