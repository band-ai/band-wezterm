"""End-to-end resource command flows through the public Cyclopts tree."""

from __future__ import annotations

from enum import StrEnum

from band_wezterm.cli import Command, create_app

ROOM_TITLE = "Delivery"
AGENT_REFERENCE = "architect"


class Event(StrEnum):
    ROOM_CREATED = "room_created"
    AGENT_STARTED = "agent_started"
    AGENTS_STOPPED = "agents_stopped"
    AGENTS_STATUS = "agents_status"


def test_resource_commands_execute_a_multi_step_session() -> None:
    events: list[tuple[Event, object]] = []

    async def create_room(title: str) -> int:
        events.append((Event.ROOM_CREATED, title))
        return 0

    async def start_agent(reference: str) -> int:
        events.append((Event.AGENT_STARTED, reference))
        return 0

    async def stop_agent(reference: str | None, all_agents: bool) -> int:
        events.append((Event.AGENTS_STOPPED, (reference, all_agents)))
        return 0

    async def status(rooms_only: bool, agents_only: bool) -> int:
        events.append((Event.AGENTS_STATUS, (rooms_only, agents_only)))
        return 0

    async def no_result() -> int:
        return 0

    async def no_agents(_verbose: bool) -> int:
        return 0

    async def no_reference(_reference: str) -> int:
        return 0

    def no_view(_reference: str | None = None) -> int:
        return 0

    app = create_app(
        setup=lambda: 0,
        room_view=no_view,
        agent_view=lambda: 0,
        create_agent=lambda: 0,
        configure_agent=lambda _reference: 0,
        rooms=no_result,
        agents=no_agents,
        create_room=create_room,
        delete_room=no_reference,
        delete_agent=no_reference,
        start_agent=start_agent,
        stop_agent=stop_agent,
        agent_status=no_reference,
        status=status,
        logs=lambda _tail: 0,
    )

    assert app([Command.ROOM, Command.CREATE, ROOM_TITLE]) == 0
    assert app([Command.AGENT, Command.START, AGENT_REFERENCE]) == 0
    assert app([Command.AGENT, Command.STOP, "--all"]) == 0
    assert app([Command.STATUS, "--agent"]) == 0

    assert events == [
        (Event.ROOM_CREATED, ROOM_TITLE),
        (Event.AGENT_STARTED, AGENT_REFERENCE),
        (Event.AGENTS_STOPPED, (None, True)),
        (Event.AGENTS_STATUS, (False, True)),
    ]
