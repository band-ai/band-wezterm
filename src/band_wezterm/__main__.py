"""`band` entrypoint for Band room and agent surfaces."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Final

from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.cli import COMMAND_NAME, AgentAction, create_app
from band_wezterm.cli_output import (
    AgentOutput,
    RoomOutput,
    print_agent,
    print_agents,
    print_rooms,
)
from band_wezterm.client import AgentRecord, BandClient, RoomRecord
from band_wezterm.diagnostics import log_event
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.resource_operations import ManagedAgentOperations, RoomOperations
from band_wezterm.setup_wezterm import (
    SetupAction,
    SetupConfigError,
    ensure_band_plugin_config,
)
from band_wezterm.supervisor import ManagedAgentLifecycle, SupervisorClient
from band_wezterm.tui.control_app import AppScreen, is_control_process, run_control_app
from band_wezterm.wezterm_cli import (
    WezTermCliError,
    WezTermNotFoundError,
    start_first_window,
)

TUI_MODULE: Final = "band_wezterm.tui"


class RoomSelectionError(ValueError):
    """A room reference does not select exactly one accessible room."""


class AgentSelectionError(ValueError):
    """An agent reference does not select exactly one registered agent."""


def _view_command(*, room_id: str | None, screen: AppScreen) -> list[str]:
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
    if screen is not AppScreen.ROOMS:
        command.extend(["--screen", screen.value])
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
    screen: AppScreen = AppScreen.ROOMS,
) -> int:
    cwd = Path.cwd()
    if os.environ.get("WEZTERM_PANE"):
        return run_control_app(initial_room_id=room_id, initial_screen=screen)
    return _start_view_without_cli(cwd, room_id=room_id, screen=screen)


def _run_room(reference: str | None) -> int:
    try:
        room_id = (
            None if reference is None else asyncio.run(_resolve_room_id(reference))
        )
        return _run_view(room_id=room_id)
    except (RoomSelectionError, ValueError, WezTermCliError) as exc:
        print(exc, file=sys.stderr)
        return 1


def _start_view_without_cli(
    cwd: Path,
    *,
    room_id: str | None,
    screen: AppScreen,
) -> int:
    """Recover when a GUI closes between a CLI lookup and spawn."""
    start_first_window(cwd, _view_command(room_id=room_id, screen=screen))
    print("Band view opened in a new WezTerm window.")
    return 0


def _run_agent_view(_reference: str | None = None) -> int:
    return _run_view(screen=AppScreen.AGENTS)


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


async def _current_lifecycle() -> ManagedAgentLifecycle:
    return ManagedAgentLifecycle(await _current_supervisor())


async def _current_agent_operations() -> tuple[ManagedAgentOperations, BandClient]:
    client = BandClient(HostAuth())
    try:
        user_id = await client.whoami()
        supervisor = SupervisorClient()
        await supervisor.connect(user_id)
    except Exception:
        await client.aclose()
        raise
    lifecycle = ManagedAgentLifecycle(supervisor)
    return ManagedAgentOperations(client, lifecycle, ManagedAgentStore()), client


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


async def _resolve_agent(reference: str) -> AgentRecord:
    agents = await _list_agents()
    matches = [
        agent
        for agent in agents
        if agent.id == reference or agent.name.casefold() == reference.casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise AgentSelectionError(f"No registered agent matches {reference!r}.")
    choices = ", ".join(f"{agent.name} ({agent.id})" for agent in matches)
    raise AgentSelectionError(
        f"{reference!r} matches multiple agents: {choices}. Use the agent ID instead."
    )


async def _run_rooms() -> int:
    rooms = await _list_rooms()
    print_rooms([_room_output(room) for room in rooms])
    return 0


async def _run_status(rooms_only: bool, agents_only: bool) -> int:
    if not agents_only:
        rooms = await _list_rooms()
        print_rooms([_room_output(room) for room in rooms])
    if not rooms_only:
        await _run_agents()
    return 0


async def _run_agents() -> int:
    agents, lifecycle = await asyncio.gather(_list_agents(), _current_lifecycle())
    workers = {worker.agent_id: worker for worker in await lifecycle.workers()}
    rows: list[AgentOutput] = []
    for agent in agents:
        worker = workers.get(agent.id)
        state = "stopped" if worker is None else worker.state.value
        action = AgentAction.START if worker is None else AgentAction.STOP
        rows.append(
            AgentOutput(
                name=agent.name,
                state=state,
                agent_id=agent.id,
                action=action.value,
            )
        )
    print_agents(rows)
    return 0


def _room_output(room: RoomRecord) -> RoomOutput:
    return RoomOutput(
        title=room.title,
        room_id=room.id,
    )


async def _run_start_agent(reference: str) -> int:
    agent = await _resolve_agent(reference)
    operations, client = await _current_agent_operations()
    try:
        worker = await operations.start(agent.id, cwd=Path.cwd())
    finally:
        await client.aclose()
    print_agent(_agent_output(worker.name, worker.agent_id, worker.state.value))
    return 0


async def _run_stop_agent(reference: str | None, all_agents: bool) -> int:
    if all_agents:
        operations, client = await _current_agent_operations()
        try:
            await operations.stop_all()
        finally:
            await client.aclose()
        print("Stopping all detached agents.")
        return 0
    assert reference is not None
    agent = await _resolve_agent(reference)
    operations, client = await _current_agent_operations()
    try:
        worker = await operations.stop(agent.id)
    finally:
        await client.aclose()
    if worker is None:
        print(f"{agent.name} is already stopped.")
    else:
        print_agent(_agent_output(worker.name, worker.agent_id, worker.state.value))
    return 0


async def _run_agent_status(reference: str) -> int:
    agent = await _resolve_agent(reference)
    lifecycle = await _current_lifecycle()
    worker = next(
        (worker for worker in await lifecycle.workers() if worker.agent_id == agent.id),
        None,
    )
    if worker is None:
        print(f"{agent.name} is stopped.")
    else:
        print_agent(_agent_output(worker.name, worker.agent_id, worker.state.value))
    return 0


def _agent_output(name: str, agent_id: str, state: str) -> AgentOutput:
    action = AgentAction.START if state == "stopped" else AgentAction.STOP
    return AgentOutput(name=name, state=state, agent_id=agent_id, action=action.value)


async def _run_create_room(title: str) -> int:
    client = BandClient(HostAuth())
    try:
        room = await RoomOperations(client).create(title)
    finally:
        await client.aclose()
    print_rooms([_room_output(room)])
    return 0


async def _run_delete_room(reference: str) -> int:
    room_id = await _resolve_room_id(reference)
    client = BandClient(HostAuth())
    try:
        await RoomOperations(client).delete(room_id)
    finally:
        await client.aclose()
    print(f"Deleted room {room_id}.")
    return 0


async def _run_delete_agent(reference: str) -> int:
    agent = await _resolve_agent(reference)
    operations, client = await _current_agent_operations()
    try:
        await operations.delete(agent.id)
    finally:
        await client.aclose()
    print(f"Deleted agent {agent.name} ({agent.id}).")
    return 0


def main(argv: list[str] | None = None) -> int:
    if is_control_process():
        return run_control_app()
    app = create_app(
        setup=_run_setup,
        room_view=_run_room,
        rooms=_run_rooms,
        agents=_run_agents,
        create_room=_run_create_room,
        delete_room=_run_delete_room,
        delete_agent=_run_delete_agent,
        start_agent=_run_start_agent,
        stop_agent=_run_stop_agent,
        agent_status=_run_agent_status,
        status=_run_status,
        agent_view=_run_agent_view,
    )
    try:
        return app(argv)
    except Exception as error:
        log_event("command failed", error_type=type(error).__name__)
        print(f"Band command failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
