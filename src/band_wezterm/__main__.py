"""`band-wezterm` entrypoint — setup, open, attach, or restart the Control tab."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Final

from band_wezterm.config import BAND_WORKSPACE_NAME, CONTROL_TAB_TITLE
from band_wezterm.setup_wezterm import SetupAction, ensure_band_plugin_config
from band_wezterm.tui.control_app import is_control_process, run_control_app
from band_wezterm.wezterm_cli import (
    PaneId,
    WezTermNotFoundError,
    WindowId,
    find_control_pane,
    kill_window,
    request_workspace_focus,
    set_tab_title,
    set_window_title,
    spawn_first_tab,
)

CONTROL_MODULE: Final = "band_wezterm.tui"
WINDOW_TITLE: Final = "Band"
SETUP_COMMAND: Final = "setup"


def _control_command() -> list[str]:
    """Spawn via ``env`` so NO_COLOR from the launcher cannot gray out Textual."""
    # macOS ``env`` has no ``--``; name=value then utility.
    return [
        "env",
        "-u",
        "NO_COLOR",
        "COLORTERM=truecolor",
        sys.executable,
        "-m",
        CONTROL_MODULE,
    ]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="band-wezterm",
        description=(
            "Open Band Control in WezTerm. Re-running attaches and raises the "
            "existing Control window; --restart replaces it. "
            f"`{SETUP_COMMAND}` wires the Band WezTerm plugin into your config."
        ),
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Kill the existing Control window and open a fresh one",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        SETUP_COMMAND,
        help="Install/update the Band WezTerm plugin snippet in ~/.wezterm.lua",
    )
    return parser.parse_args(argv)


def _spawn_control(cwd: Path) -> tuple[WindowId, PaneId]:
    spawned = spawn_first_tab(cwd, _control_command())
    set_tab_title(spawned.pane_id, CONTROL_TAB_TITLE)
    set_window_title(spawned.pane_id, WINDOW_TITLE)
    return spawned.window_id, spawned.pane_id


def _retire_legacy_band_workspace(control_window: WindowId) -> None:
    """Drop Control that was spawned into the hidden ``band`` workspace."""
    kill_window(control_window)


def _run_setup() -> int:
    try:
        result = ensure_band_plugin_config()
    except WezTermNotFoundError as exc:
        print(
            f"{exc} — install WezTerm first (e.g. `brew install --cask wezterm`)",
            file=sys.stderr,
        )
        return 1

    match result.action:
        case SetupAction.CREATED:
            print(f"Created {result.path} with the Band WezTerm plugin.")
        case SetupAction.UPDATED:
            print(f"Updated Band WezTerm plugin block in {result.path}.")
        case SetupAction.UNCHANGED:
            print(f"Band WezTerm plugin already configured in {result.path}.")
    print(
        "Reload WezTerm config (Ctrl+Shift+R) or restart WezTerm, then run "
        "`band-wezterm`."
    )
    return 0


def _run_control(*, restart: bool) -> int:
    cwd = Path.cwd()
    existing = find_control_pane()

    if existing is not None and existing.workspace == BAND_WORKSPACE_NAME:
        # Pre-fix spawns used --workspace band and stay invisible until the GUI
        # switches workspaces (no CLI for that). Replace with a visible window.
        _retire_legacy_band_workspace(WindowId(existing.window_id))
        existing = None

    if restart and existing is not None:
        kill_window(WindowId(existing.window_id))
        existing = None

    if existing is not None:
        window_id = WindowId(existing.window_id)
        pane_id = PaneId(existing.pane_id)
        action = "attached"
    else:
        window_id, pane_id = _spawn_control(cwd)
        action = "restarted" if restart else "opened"

    request_workspace_focus(control_pane=pane_id)
    print(
        f"Control tab {action} in window {window_id.root} "
        f"(pane {pane_id.root})."
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    if is_control_process():
        return run_control_app()

    args = _parse_args(argv)
    if args.command == SETUP_COMMAND:
        return _run_setup()
    return _run_control(restart=args.restart)


if __name__ == "__main__":
    raise SystemExit(main())
