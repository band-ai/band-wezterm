"""`band` entrypoint — open a Band home or room view in the current pane."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Final

from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.cli import COMMAND_NAME, AgentAction, Command, create_app
from band_wezterm.client import AgentRecord, BandClient, RoomRecord
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

TUI_MODULE: Final = "band_wezterm.tui"
STATUS_ROOMS_HEADING: Final = "Rooms"
STATUS_AGENTS_HEADING: Final = "Agents"
STATUS_EMPTY_ROOMS: Final = "No accessible rooms."
STATUS_EMPTY_AGENTS: Final = "No managed agents are running."


class RoomSelectionError(ValueError):
    """A room reference does not select exactly one accessible room."""


def _view_command(*, room_id: str | None) -> list[str]:
    """Spawn via ``env`` so NO_COLOR from the launcher cannot gray out Textual."""
    # macOS ``env`` has no ``--``; name=value then utility.
    command = [
        "env",
        "-u",
        "NO_COLOR",
        "COLORTERM=truecolor",
        sys.executable,
        "-m",
        TUI_MODULE,
    ]
    if room_id is not None:
        command.extend(["--room-id", room_id])
    return command


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


def _run_view(
    *,
    room_id: str | None = None,
) -> int:
    cwd = Path.cwd()
    if os.environ.get("WEZTERM_PANE"):
        return run_control_app(initial_room_id=room_id)
    return _start_view_without_cli(cwd, room_id=room_id)


async def _run_room(reference: str | None) -> int:
    try:
        room_id = None if reference is None else await _resolve_room_id(reference)
        return _run_view(room_id=room_id)
    except (RoomSelectionError, ValueError, WezTermCliError) as exc:
        print(exc, file=sys.stderr)
        return 1


def _start_view_without_cli(
    cwd: Path,
    *,
    room_id: str | None,
) -> int:
    """Recover when a GUI closes between a CLI lookup and spawn."""
    start_first_window(cwd, _view_command(room_id=room_id))
    print("Band view opened in a new WezTerm window.")
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


async def _list_rooms() -> list[RoomRecord]:
    """Read the current user's accessible room catalog."""
    auth = HostAuth()
    client = BandClient(auth)
    try:
        return await client.list_my_chats()
    finally:
        await client.aclose()


async def _list_agents() -> list[AgentRecord]:
    """Read the current user's registered agents."""
    auth = HostAuth()
    client = BandClient(auth)
    try:
        return await client.list_my_agents()
    finally:
        await client.aclose()


async def _resolve_room_id(reference: str) -> str:
    """Resolve an exact room title or ID for the direct room command."""
    rooms = await _list_rooms()
    matches = [
        room
        for room in rooms
        if room.id == reference or room.title.casefold() == reference.casefold()
    ]
    if len(matches) == 1:
        return matches[0].id
    if not matches:
        raise RoomSelectionError(
            f"No accessible room matches {reference!r}. Run `band room` to choose a room."
        )
    choices = ", ".join(f"{room.title} ({room.id})" for room in matches)
    raise RoomSelectionError(
        f"{reference!r} matches multiple rooms: {choices}. Use the room ID instead."
    )


async def _run_rooms() -> int:
    rooms = await _list_rooms()
    if not rooms:
        print("No accessible rooms.")
        return 0
    for room in rooms:
        print(f"{room.title}\t{room.id}")
    return 0


async def _run_status() -> int:
    rooms = await _list_rooms()
    print(STATUS_ROOMS_HEADING)
    if not rooms:
        print(STATUS_EMPTY_ROOMS)
    for room in rooms:
        print(f"{room.title}\t{room.id}\t{COMMAND_NAME} {Command.ROOM.value} {room.id}")
    print()
    await _run_agents()
    return 0


async def _run_agents() -> int:
    agents, supervisor = await asyncio.gather(_list_agents(), _current_supervisor())
    workers = {worker.agent_id: worker for worker in await supervisor.list_workers()}
    print(STATUS_AGENTS_HEADING)
    if not agents:
        print(STATUS_EMPTY_AGENTS)
        return 0
    for agent in agents:
        worker = workers.get(agent.id)
        state = "stopped" if worker is None else worker.state.value
        action = AgentAction.START if worker is None else AgentAction.STOP
        print(
            f"{agent.name}\t{agent.id}\t{state}\t{COMMAND_NAME} "
            f"{Command.AGENT.value} {action.value} {agent.id}"
        )
    return 0


async def _run_agent_action(action: AgentAction, agent_id: str) -> int:
    """Perform one lifecycle operation on a managed agent."""
    supervisor = await _current_supervisor()
    match action:
        case AgentAction.START:
            worker = await supervisor.start(agent_id, cwd=Path.cwd())
            print(
                f"{worker.name}\t{worker.agent_id}\t{worker.state.value}\tpid {worker.pid}"
            )
        case AgentAction.STOP:
            worker = await supervisor.stop(agent_id)
            if worker is None:
                print(f"{agent_id} is already stopped.")
            else:
                print(f"{worker.name}\t{worker.agent_id}\t{worker.state.value}")
        case AgentAction.STATUS:
            worker = next(
                (
                    worker
                    for worker in await supervisor.list_workers()
                    if worker.agent_id == agent_id
                ),
                None,
            )
            if worker is None:
                print(f"{agent_id} is stopped.")
            else:
                print(
                    f"{worker.name}\t{worker.agent_id}\t{worker.state.value}\t"
                    f"pid {worker.pid}\t{worker.cwd}"
                )
    return 0


def main(argv: list[str] | None = None) -> int:
    if is_control_process():
        return run_control_app()
    app = create_app(
        setup=_run_setup,
        room=_run_room,
        rooms=_run_rooms,
        agents=_run_agents,
        status=_run_status,
        agent=_run_agent_action,
    )
    return asyncio.run(app.run_async(argv))


if __name__ == "__main__":
    raise SystemExit(main())
