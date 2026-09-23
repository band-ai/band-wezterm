<div align="center">

<img src="docs/images/band-matrix-logo.png" alt="Band" width="240">

# Band for WezTerm

[![CI](https://github.com/band-ai/band-wezterm/actions/workflows/ci.yml/badge.svg)](https://github.com/band-ai/band-wezterm/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Band rooms and managed agents, in the WezTerm layout you already use.**

Every Band view is disposable. Managed agents are detached workers: closing a tab, split, or window never stops them.

[Install](#install) · [Daily use](#daily-use) · [Lifecycle](#agent-lifecycle) · [Development](#development)

</div>

<p align="center">
  <img src="docs/images/room-view.svg" alt="A Band room open in WezTerm">
</p>

## The model

Band follows WezTerm rather than replacing it. Create tabs, panes, and windows with your normal workflow; run a Band command in the pane where you want that surface to live.

| You own | Band owns |
| --- | --- |
| Windows, tabs, splits, focus, and key bindings | Rooms, messages, participant roster, roles, and managed-agent workers |
| Where and how many views are open | An agent's durable profile and detached runtime |

There is no global Control window to find or reuse. `band room` and `band agent` each open an independent surface. You can have any number of either, including two views of the same room. Closing them only closes the view.

## Install

Install [Python 3.12+](https://www.python.org/downloads/), [uv](https://github.com/astral-sh/uv), [WezTerm](https://wezterm.org/), and [GitHub CLI](https://cli.github.com/). Authenticate GitHub once with `gh auth login` for this private repository.

### Stable release

```bash
gh release download --repo band-ai/band-wezterm --pattern install.sh --output - | bash -s -- --release
```

```powershell
$installer = Join-Path ([System.IO.Path]::GetTempPath()) "band-wezterm-install.ps1"
gh release download --repo band-ai/band-wezterm --pattern install.ps1 --output $installer --clobber
& $installer -Channel release
Remove-Item $installer
```

### From source

```bash
git clone --branch main --single-branch https://github.com/band-ai/band-wezterm.git
cd band-wezterm
./install.sh
```

The installer configures the WezTerm plugin. Reload WezTerm configuration (`Ctrl+Shift+R`) and run `band` for command help.

## Daily use

Start with normal WezTerm layout commands, then place Band where you need it:

```text
wezterm tab / split / window
          │
          ├── band room              # room browser and room management
          ├── band room open NAME_OR_ID
          └── band agent             # agent and role management
```

| Command | Purpose |
| --- | --- |
| `band` | Show help. It never opens a view. |
| `band room` | Open Rooms: browse, create, select, and manage rooms. |
| `band room open NAME_OR_ID` | Open one accessible room directly. |
| `band room list` | List rooms with IDs and direct open commands. |
| `band room create TITLE` | Create a room. |
| `band room delete NAME_OR_ID` | Delete one room. |
| `band agent` | Open Agents: register, configure, manage roles, start, stop, or delete agents. |
| `band agent list` | List registered agents, detached runtime state, and next command. |
| `band agent create` | Open the agent registration wizard directly. |
| `band agent configure NAME_OR_ID` | Open reconfiguration for one exact agent. |
| `band status` | Show Rooms and Agents as separate operational tables. |
| `band agent start AGENT_ID` | Start one detached managed worker. |
| `band agent stop AGENT_ID` | Gracefully stop one detached managed worker. |
| `band agent status AGENT_ID` | Inspect one detached managed worker. |
| `band agent stop --all` | Gracefully stop every detached managed worker. |
| `band agent delete AGENT_ID` | Stop and delete one agent. |
| `band status --room` / `--agent` | Show only the selected status table. |
| `band setup` | Install or update the Band WezTerm plugin configuration. |

`band status --room` and `band status --agent` are mutually exclusive. So are an agent reference and `--all` in `band agent stop`. The surface uses local, context-specific keys and does not reserve global Ctrl- or function-key bindings. WezTerm shortcuts remain yours.

### Rooms

`band room` opens the complete room experience: create a room, filter the list, open a room, add participants, chat, and start or stop a selected managed participant. In the composer, type `@` plus a visible participant name; Tab or Right Arrow completes the mention.

Run the command again anywhere to open another independent Room surface.

### Agents and roles

`band agent` opens the dedicated Agents experience. Press `n` to register an agent through runtime, role, name, description, and model/reasoning choices. Use `c` to reconfigure, `s`/`x` to start/stop the selected agent, and `Delete` to remove it.

`band agent create` opens that registration wizard immediately. `band agent configure NAME_OR_ID` resolves one exact agent first, then opens its reconfiguration wizard; it never silently falls back to an unselected list. The list remains the right surface for browsing, runtime status, role management, and ad-hoc lifecycle actions.

Roles are Markdown personas in `~/.band/roles`. Default roles are seeded on first use. A registered agent saves a role snapshot and tuning as its durable local profile; reconfigure it to adopt later role edits.

<p align="center">
  <img src="docs/images/agent-register.svg" alt="Registering an agent in the Band Agents surface">
</p>

## Agent lifecycle

An agent is not a WezTerm pane. Starting an agent asks the local, authenticated supervisor to launch one detached Band SDK worker. That worker subscribes to the agent's rooms and continues after every Band view is closed.

```text
band agent start AGENT_ID
          │
          ▼
local supervisor ── launches ──► detached worker ──► Band rooms
          ▲                              │
          └──── any room/agent view ─────┘
```

Workers stop only when you explicitly Stop them, delete their agent, sign out, the worker encounters a fatal error, or the machine/process shuts down. A later `band room`, `band agent`, `band agent list`, or `band status` reconnects to the same local supervisor and reports the still-running worker.

Each profile selects Claude, Codex, Copilot, or OpenCode. Host-side authentication for the selected runtime must already work. Install all adapters with `uv sync --extra agents`, or install individual extras as needed.

## Configuration and security

OAuth targets production Band by default. To use another deployment, set `BAND_OAUTH_ISSUER`, `BAND_BASE_URL` (or `BAND_REST_URL`), and `BAND_WS_URL` together. `BAND_OAUTH_CLIENT_ID` selects another public OAuth client.

Tokens and managed-agent API keys are stored only in the OS keyring. Diagnostic logs redact tokens, request headers, and message bodies. OSC user variables carry only allowlisted display metadata.

## Development

```bash
just sync            # core + development tools
just sync-agents     # all agent runtime extras
just setup           # update local WezTerm plugin configuration
just test            # unit tests
just test-wezterm    # live WezTerm CLI checks
just test-live       # live platform PTY checks; requires BAND_API_KEY_USER
just screenshots     # refresh README SVGs without WezTerm or platform access
```

`plugin/init.lua` is the source of truth for the WezTerm plugin. Re-run `band setup` after editing it, reload WezTerm configuration, and use `wezterm.plugin.update_all()` from the Debug Overlay when needed.

## License

[MIT](LICENSE) © band.ai
