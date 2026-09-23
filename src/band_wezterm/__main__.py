"""`band` entrypoint for Band room and agent surfaces."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Final

from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.cli import COMMAND_NAME, create_app
from band_wezterm.cli_output import (
    AgentOutput,
    RoomOutput,
    print_agent,
    print_agents,
    print_rooms,
)
from band_wezterm.client import AgentRecord, BandClient, RoomRecord
from band_wezterm.config import load_settings
from band_wezterm.diagnostics import configure_diagnostics, log_event, read_diagnostics
from band_wezterm.listing import ListQuery, paginate
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.resource_operations import ManagedAgentOperations, RoomOperations
from band_wezterm.setup_wezterm import (
    SetupAction,
    SetupConfigError,
    ensure_band_plugin_config,
)
from band_wezterm.supervisor import ManagedAgentLifecycle, SupervisorClient
from band_wezterm.tui.control_app import (
    AppScreen,
    InitialAgentAction,
    is_control_process,
    run_control_app,
)
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


def _view_command(
    *,
    room_id: str | None,
    screen: AppScreen,
    agent_action: InitialAgentAction = InitialAgentAction.BROWSE,
    agent_id: str | None = None,
) -> list[str]:
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
    if agent_action is not InitialAgentAction.BROWSE:
        command.extend(["--agent-action", agent_action.value])
    if agent_id is not None:
        command.extend(["--agent-id", agent_id])
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
    agent_action: InitialAgentAction = InitialAgentAction.BROWSE,
    agent_id: str | None = None,
) -> int:
    cwd = Path.cwd()
    if os.environ.get("WEZTERM_PANE"):
        if agent_action is InitialAgentAction.BROWSE and agent_id is None:
            return run_control_app(initial_room_id=room_id, initial_screen=screen)
        return run_control_app(
            initial_room_id=room_id,
            initial_screen=screen,
            initial_agent_action=agent_action,
            initial_agent_id=agent_id,
        )
    return _start_view_without_cli(
        cwd,
        room_id=room_id,
        screen=screen,
        agent_action=agent_action,
        agent_id=agent_id,
    )


def _run_room(reference: str | None) -> int:
    try:
        room_id = None if reference is None else asyncio.run(_resolve_room_id(reference))
        return _run_view(room_id=room_id)
    except (RoomSelectionError, ValueError, WezTermCliError) as exc:
        print(exc, file=sys.stderr)
        return 1


def _start_view_without_cli(
    cwd: Path,
    *,
    room_id: str | None,
    screen: AppScreen,
    agent_action: InitialAgentAction,
    agent_id: str | None,
) -> int:
    """Recover when a GUI closes between a CLI lookup and spawn."""
    start_first_window(
        cwd,
        _view_command(
            room_id=room_id,
            screen=screen,
            agent_action=agent_action,
            agent_id=agent_id,
        ),
    )
    print("Band view opened in a new WezTerm window.")
    return 0


def _run_agent_view_for_reference(reference: str | None) -> int:
    try:
        agent_id = None if reference is None else asyncio.run(_resolve_agent(reference)).id
    except (AgentSelectionError, ValueError, WezTermCliError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return _run_view(screen=AppScreen.AGENTS, agent_id=agent_id)


def _run_create_agent() -> int:
    return _run_view(
        screen=AppScreen.AGENTS,
        agent_action=InitialAgentAction.CREATE,
    )


def _run_configure_agent(reference: str) -> int:
    try:
        agent = asyncio.run(_resolve_agent(reference))
    except (AgentSelectionError, ValueError, WezTermCliError) as exc:
        print(exc, file=sys.stderr)
        return 1
    return _run_view(
        screen=AppScreen.AGENTS,
        agent_action=InitialAgentAction.CONFIGURE,
        agent_id=agent.id,
    )


async def _current_supervisor() -> SupervisorClient:
    settings = load_settings()
    auth = HostAuth(settings)
    client = BandClient(auth, settings)
    try:
        user_id = await client.whoami()
    finally:
        await client.aclose()
    supervisor = SupervisorClient(settings=settings)
    await supervisor.connect(user_id)
    return supervisor


async def _current_lifecycle() -> ManagedAgentLifecycle:
    return ManagedAgentLifecycle(await _current_supervisor())


async def _current_agent_operations() -> tuple[ManagedAgentOperations, BandClient]:
    settings = load_settings()
    client = BandClient(HostAuth(settings), settings)
    try:
        user_id = await client.whoami()
        supervisor = SupervisorClient(settings=settings)
        await supervisor.connect(user_id)
    except Exception:
        await client.aclose()
        raise
    lifecycle = ManagedAgentLifecycle(supervisor)
    return ManagedAgentOperations(
        client, lifecycle, ManagedAgentStore(settings=settings)
    ), client


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
    """Resolve an exact room title or a unique room ID prefix."""
    rooms = await _list_rooms()
    normalized_reference = reference.casefold()
    exact_matches = [
        room
        for room in rooms
        if room.id.casefold() == normalized_reference
        or room.title.casefold() == normalized_reference
    ]
    if len(exact_matches) == 1:
        return exact_matches[0].id
    matches = [
        room for room in rooms if room.id.casefold().startswith(normalized_reference)
    ]
    if len(matches) == 1:
        return matches[0].id
    if not matches:
        raise RoomSelectionError(
            f"No accessible room matches {reference!r}. Run `band room` to choose a room."
        )
    choices = ", ".join(f"{room.title} ({room.id})" for room in matches)
    raise RoomSelectionError(
        f"{reference!r} matches multiple rooms: {choices}. Enter more of the ID."
    )


async def _resolve_agent(reference: str) -> AgentRecord:
    """Resolve an exact agent name or a unique agent ID prefix."""
    agents = await _list_agents()
    normalized_reference = reference.casefold()
    exact_matches = [
        agent
        for agent in agents
        if agent.id.casefold() == normalized_reference
        or agent.name.casefold() == normalized_reference
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    matches = [
        agent for agent in agents if agent.id.casefold().startswith(normalized_reference)
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise AgentSelectionError(f"No registered agent matches {reference!r}.")
    choices = ", ".join(f"{agent.name} ({agent.id})" for agent in matches)
    raise AgentSelectionError(
        f"{reference!r} matches multiple agents: {choices}. Enter more of the ID."
    )


async def _run_rooms(query: ListQuery) -> int:
    page = paginate(await _list_rooms(), query, display_name=lambda room: room.title)
    print_rooms([_room_output(room) for room in page.items], query=query, page=page.info)
    return 0


async def _run_status(rooms_only: bool, agents_only: bool) -> int:
    if not agents_only:
        await _run_rooms(ListQuery())
    if not rooms_only:
        await _run_agents(ListQuery())
    return 0


async def _run_agents(query: ListQuery, verbose: bool = False) -> int:
    agents, lifecycle = await asyncio.gather(_list_agents(), _current_lifecycle())
    workers = {worker.agent_id: worker for worker in await lifecycle.workers()}
    profiles = ManagedAgentStore()
    rows: list[AgentOutput] = []
    for agent in agents:
        worker = workers.get(agent.id)
        state = "stopped" if worker is None else worker.state.value
        rows.append(
            AgentOutput(
                name=agent.name,
                state=state,
                agent_id=agent.id,
                harness=_agent_harness(agent, profiles),
                pid=None if worker is None else worker.pid,
            )
        )
    page = paginate(
        rows,
        query,
        display_name=lambda agent: agent.name,
        predicate=lambda agent: query.matches_agent(
            harness=agent.harness, state=agent.state
        ),
    )
    print_agents(list(page.items), query=query, page=page.info, verbose=verbose)
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
    print_agent(
        _agent_output(
            worker.name,
            worker.agent_id,
            worker.state.value,
            harness=_agent_harness(agent, ManagedAgentStore()),
            pid=worker.pid,
        )
    )
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
        print_agent(
            _agent_output(
                worker.name,
                worker.agent_id,
                worker.state.value,
                harness=_agent_harness(agent, ManagedAgentStore()),
                pid=worker.pid,
            )
        )
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
        print_agent(
            _agent_output(
                worker.name,
                worker.agent_id,
                worker.state.value,
                harness=_agent_harness(agent, ManagedAgentStore()),
                pid=worker.pid,
            )
        )
    return 0


def _agent_output(
    name: str,
    agent_id: str,
    state: str,
    *,
    harness: str | None = None,
    pid: int | None = None,
) -> AgentOutput:
    return AgentOutput(
        name=name,
        state=state,
        agent_id=agent_id,
        harness=harness,
        pid=pid,
    )


def _agent_harness(agent: AgentRecord, profiles: ManagedAgentStore) -> str | None:
    harness = getattr(agent, "harness", None) or profiles.harness_for(agent.id)
    return None if harness is None else harness.value


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


def _run_logs(tail: int) -> int:
    print(read_diagnostics(lines=tail))
    return 0


def main(argv: list[str] | None = None) -> int:
    configure_diagnostics()
    if is_control_process():
        return run_control_app()
    app = create_app(
        setup=_run_setup,
        room_view=_run_room,
        rooms=_run_rooms,
        agents=_run_agents,
        create_agent=_run_create_agent,
        configure_agent=_run_configure_agent,
        create_room=_run_create_room,
        delete_room=_run_delete_room,
        delete_agent=_run_delete_agent,
        start_agent=_run_start_agent,
        stop_agent=_run_stop_agent,
        agent_status=_run_agent_status,
        status=_run_status,
        logs=_run_logs,
        agent_view=_run_agent_view_for_reference,
    )
    try:
        return app(argv)
    except Exception as error:
        log_event("command failed", error_type=type(error).__name__)
        print(f"Band command failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
