# Architecture map

Band separates disposable WezTerm views from durable agent workers. The
directories below follow that boundary so a feature has one obvious home.

| Area | Location | Add or change here |
| --- | --- | --- |
| Commands | `cli.py`, `__main__.py`, `cli_output.py` | Command shape, invocation orchestration, terminal tables |
| Resource behavior | `resource_operations.py` | Shared room/agent mutations used by commands and screens |
| Harnesses | `harnesses/` | A new model runtime, adapter construction, catalog discovery, aliases, and UI metadata |
| Worker runtime | `agent/`, `supervisor/` | Detached process launch, readiness, and lifecycle supervision |
| Platform and persistence | `client.py`, `platform_models.py`, `managed_profiles.py` | Band API boundary and durable local agent configuration |
| TUI shell | `tui/control_app.py`, `tui/screens/` | App composition and one file per user-facing screen |
| TUI shared behavior | `tui/stores.py`, `tui/widgets.py`, `tui/refresh.py` | State projection, reusable presentation, and refresh policy |

## Adding a harness

Create one `HarnessProvider` in `harnesses/providers.py` and include it in
`BUILTIN_HARNESSES`. Its `HarnessBackend` defines display and tuning metadata;
`build_adapter()` owns SDK-specific construction; `load_catalog()` owns live
model discovery. `HarnessRegistry` supplies canonical IDs, aliases, adapter
dispatch, catalog dispatch, and backend lookup to every caller. Do not add
separate alias maps or `match` branches elsewhere.

## Adding a command or screen

Add a command declaration to `cli.py`; keep its handler in `__main__.py` until
the handler becomes reusable application behavior, then put that behavior in
`resource_operations.py`. Add a screen under `tui/screens/`, register it in
`ControlApp.SCREENS`, and invoke the same operation used by the CLI. A screen
must not spawn or stop workers directly.
