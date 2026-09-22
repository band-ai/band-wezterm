"""`band` entrypoint — open a Control or room view in the current pane."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from filelock import FileLock, Timeout

from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.client import BandClient
from band_wezterm.config import LOCAL_STATE_DIRNAME
from band_wezterm.setup_wezterm import (
    SetupAction,
    SetupConfigError,
    ensure_band_plugin_config,
)
from band_wezterm.supervisor import SupervisorClient
from band_wezterm.tui.control_app import is_control_process, run_control_app
from band_wezterm.wezterm_cli import (
    WezTermCliError,
    WezTermNotFoundError,
    start_first_window,
)

CONTROL_MODULE: Final = "band_wezterm.tui"
COMMAND_NAME: Final = "band"
SETUP_COMMAND: Final = "setup"
CONTROL_LOCK_FILENAME: Final = "control-launch.lock"
CONTROL_LOCK_TIMEOUT_SECONDS: Final = 10
SETUP_HELP: Final = (
    "Install/update the Band WezTerm plugin snippet in the active "
    "WezTerm config (WEZTERM_CONFIG_FILE, ~/.wezterm.lua, or XDG wezterm.lua)"
)


class ControlLaunchError(RuntimeError):
    """Another Band Control launch did not complete in time."""


class RoomSelectionError(ValueError):
    """A room reference does not select exactly one accessible room."""


def _control_lock_path() -> Path:
    return Path.home() / LOCAL_STATE_DIRNAME / CONTROL_LOCK_FILENAME


@contextmanager
def _control_launch_lock() -> Iterator[None]:
    lock_path = _control_lock_path()
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with FileLock(lock_path, timeout=CONTROL_LOCK_TIMEOUT_SECONDS):
            yield
    except Timeout as error:
        raise ControlLaunchError(
            "Another Band Control launch is still in progress; try again shortly."
        ) from error


def _control_command(*, room_id: str | None) -> list[str]:
    """Spawn via ``env`` so NO_COLOR from the launcher cannot gray out Textual."""
    # macOS ``env`` has no ``--``; name=value then utility.
    command = [
        "env",
        "-u",
        "NO_COLOR",
        "COLORTERM=truecolor",
        sys.executable,
        "-m",
        CONTROL_MODULE,
    ]
    if room_id is not None:
        command.extend(["--room-id", room_id])
    return command


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=COMMAND_NAME,
        description=(
            "Open Band Control in this WezTerm pane. Use `band room NAME_OR_ID` "
            "to open a room directly, or `band room` to choose one in Control. "
            f"`{SETUP_COMMAND}` wires the Band WezTerm plugin into your config."
        ),
    )
    parser.add_argument(
        "--restart",
        action="store_true",
        help="Open a fresh Control view (kept for command compatibility)",
    )
    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser(
        SETUP_COMMAND,
        help=SETUP_HELP,
        description=SETUP_HELP,
    )
    room = subparsers.add_parser(
        "room",
        help="Open a room by title or ID, or choose one in Control",
    )
    room.add_argument("room", nargs="?")
    subparsers.add_parser("status", help="List detached managed agents")
    stop = subparsers.add_parser("stop", help="Gracefully stop a managed agent")
    stop.add_argument("agent_id", nargs="?")
    stop.add_argument("--all", action="store_true", dest="stop_all")
    subparsers.add_parser("help", help="Show command and workflow help")
    return parser


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    return _argument_parser().parse_args(argv)


def _run_setup() -> int:
    try:
        result = ensure_band_plugin_config()
    except WezTermNotFoundError as exc:
        print(
            f"{exc} — install WezTerm first (e.g. `brew install --cask wezterm`)",
            file=sys.stderr,
        )
        return 1
    except (SetupConfigError, OSError, UnicodeError) as exc:
        print(f"{exc}", file=sys.stderr)
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
        f"`{COMMAND_NAME}`."
    )
    return 0


def _run_control(*, room_id: str | None = None) -> int:
    with _control_launch_lock():
        return _run_control_locked(room_id=room_id)


def _run_control_locked(*, room_id: str | None) -> int:
    cwd = Path.cwd()
    if os.environ.get("WEZTERM_PANE"):
        return run_control_app(initial_room_id=room_id)
    return _start_control_without_cli(cwd, room_id=room_id)


def _start_control_without_cli(cwd: Path, *, room_id: str | None) -> int:
    """Recover when a GUI closes between a CLI lookup and spawn."""
    start_first_window(cwd, _control_command(room_id=room_id))
    print("Control tab opened in a new WezTerm window.")
    return 0


async def _current_supervisor() -> SupervisorClient:
    auth = HostAuth()
    client = BandClient(auth)
    try:
        user_id = await client.whoami()
    finally:
        await client.aclose()
    supervisor = SupervisorClient()
    await supervisor.connect(user_id)
    return supervisor


async def _resolve_room_id(reference: str) -> str:
    """Resolve an exact room title or ID for the direct room command."""
    auth = HostAuth()
    client = BandClient(auth)
    try:
        rooms = await client.list_my_chats()
    finally:
        await client.aclose()
    matches = [
        room
        for room in rooms
        if room.id == reference or room.title.casefold() == reference.casefold()
    ]
    if len(matches) == 1:
        return matches[0].id
    if not matches:
        raise RoomSelectionError(
            f"No accessible room matches {reference!r}. Run `band` to choose a room."
        )
    choices = ", ".join(f"{room.title} ({room.id})" for room in matches)
    raise RoomSelectionError(
        f"{reference!r} matches multiple rooms: {choices}. Use the room ID instead."
    )


async def _run_status() -> int:
    supervisor = await _current_supervisor()
    workers = await supervisor.list_workers()
    if not workers:
        print("No managed agents are running.")
        return 0
    for worker in workers:
        print(
            f"{worker.name}\t{worker.agent_id}\t{worker.state.value}\tpid {worker.pid}"
        )
    return 0


async def _run_stop(*, agent_id: str | None, all_workers: bool) -> int:
    if all_workers == (agent_id is not None):
        raise ValueError("Use `band stop AGENT_ID` or `band stop --all`.")
    supervisor = await _current_supervisor()
    if all_workers:
        await supervisor.stop_all()
        print("Stop requested for all managed agents.")
    else:
        assert agent_id is not None
        await supervisor.stop(agent_id)
        print(f"Stop requested for {agent_id}.")
    return 0


def main(argv: list[str] | None = None) -> int:
    if is_control_process():
        return run_control_app()
    args = _parse_args(argv)
    if args.command == SETUP_COMMAND:
        return _run_setup()
    if args.command == "help":
        _argument_parser().print_help()
        return 0
    try:
        if args.command == "status":
            return asyncio.run(_run_status())
        if args.command == "stop":
            return asyncio.run(
                _run_stop(agent_id=args.agent_id, all_workers=args.stop_all)
            )
        room_id = (
            asyncio.run(_resolve_room_id(args.room))
            if args.command == "room" and args.room is not None
            else None
        )
        return _run_control(room_id=room_id)
    except (ControlLaunchError, RoomSelectionError, ValueError, WezTermCliError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
