"""Pilot tests for the Control tab behaviors that are easy to regress."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from textual.containers import Vertical
from textual.widgets import Input, ListView

from band_wezterm.client import MessageRecord
from band_wezterm.tui.control_app import ControlApp
from band_wezterm.tui.screens.agents import OPEN_CLASS, AgentRow, AgentsScreen
from band_wezterm.tui.screens.agents import Id as AgentId
from band_wezterm.tui.screens.agents import selector as agent_selector
from band_wezterm.tui.screens.rooms import Id as RoomId
from band_wezterm.tui.screens.rooms import IdentityRow, RoomDetailScreen, RoomsScreen
from band_wezterm.tui.screens.rooms import selector as room_selector
from band_wezterm.wezterm_cli import PaneId

from .conftest import agent, participant, room, settle

RUNNING_AGENT_ID = "0f5d0b7c-1a3e-4c5b-9d2f-6a7b8c9d0e1f"
IDLE_AGENT_ID = "3c2b1a09-8f7e-4d6c-5b4a-3928176054f3"
ROOM_ID = "9a8b7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d"
AGENT_PANE = PaneId(11)


def listed_agents(app: ControlApp) -> list[str]:
    return [row.agent.name for row in app.screen.query(AgentRow)]


def offered_candidates(app: ControlApp) -> list[str]:
    picker = app.screen.query_one(room_selector(RoomId.PICKER_LIST), ListView)
    return [row.identity.name for row in picker.query(IdentityRow)]


@pytest.fixture
def running_and_idle(control_app: ControlApp, band_client: MagicMock) -> None:
    band_client.list_my_agents.return_value = [
        agent(RUNNING_AGENT_ID, "Alpha"),
        agent(IDLE_AGENT_ID, "Beta"),
    ]
    control_app.agents_store.mark_running(RUNNING_AGENT_ID, AGENT_PANE)


@pytest.mark.usefixtures("running_and_idle")
async def test_chips_and_search_narrow_together(control_app: ControlApp) -> None:
    """One chip at a time (All = none); search still narrows on top."""
    async with control_app.run_test() as pilot:
        await settle(pilot)
        assert listed_agents(control_app) == ["Alpha", "Beta"]

        # All is first; move to Running and select it.
        await pilot.press("f", "right", "space")
        await settle(pilot)
        assert listed_agents(control_app) == ["Alpha"]

        await pilot.press("slash", *"beta")
        await settle(pilot)
        assert listed_agents(control_app) == []


async def test_switching_screens_discards_the_open_draft(
    control_app: ControlApp,
) -> None:
    """A half-typed registration must not survive a trip through Rooms."""
    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n", *"half-typed")
        await settle(pilot)
        assert control_app.agents_store.draft_open is True

        await pilot.press("ctrl+o")
        await settle(pilot)
        assert isinstance(control_app.screen, RoomsScreen)
        assert control_app.agents_store.draft_open is False

        await pilot.press("ctrl+a")
        await settle(pilot)
        draft = control_app.screen.query_one(agent_selector(AgentId.DRAFT), Vertical)
        draft_name = control_app.screen.query_one(
            agent_selector(AgentId.DRAFT_NAME), Input
        )
        assert draft.has_class(OPEN_CLASS) is False
        assert draft_name.value == ""


async def test_add_participant_only_adds(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    """The picker offers non-members only, and adding never removes anyone."""
    member = agent(RUNNING_AGENT_ID, "Alpha")
    candidate = agent(IDLE_AGENT_ID, "Beta")
    band_client.list_participants.return_value = [participant(member)]
    band_client.list_my_agents.return_value = [member, candidate]
    target = room(ROOM_ID, "Core")

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target)
        await settle(pilot)
        assert isinstance(control_app.screen, RoomDetailScreen)

        await pilot.press("a")
        await settle(pilot)
        assert offered_candidates(control_app) == ["Beta"]

        await pilot.press("enter")
        await settle(pilot)

    band_client.add_participant.assert_awaited_once_with(ROOM_ID, IDLE_AGENT_ID)
    band_client.remove_participant.assert_not_awaited()


async def test_agents_screen_is_the_entry_point_once_signed_in(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    async with control_app.run_test() as pilot:
        await settle(pilot)
        assert isinstance(control_app.screen, AgentsScreen)
        assert control_app.screen.query_one(
            agent_selector(AgentId.LIST), ListView
        ).has_focus
    band_client.whoami.assert_awaited_once()


async def test_unmount_stops_every_agent_tab_the_host_started(
    control_app: ControlApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[PaneId] = []
    monkeypatch.setattr("band_wezterm.tui.control_app.kill_pane", killed.append)
    control_app.agents_store.mark_running(RUNNING_AGENT_ID, AGENT_PANE)

    async with control_app.run_test() as pilot:
        await settle(pilot)

    assert killed == [AGENT_PANE]
    assert control_app.agents_store.running == {}


async def test_opening_a_room_loads_message_history(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    """Room enter must REST-fetch history — realtime alone is not enough."""
    history = [
        MessageRecord(id="m1", content="@omp hello", author_name="user1 ci"),
        MessageRecord(id="m2", content="hi back", author_name="omp"),
    ]
    band_client.list_messages.return_value = history
    band_client.list_participants.return_value = []
    target = room(ROOM_ID, "Core")

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target)
        await settle(pilot)
        assert isinstance(control_app.screen, RoomDetailScreen)
        assert [m.id for m in control_app.rooms_store.messages] == ["m1", "m2"]

    band_client.list_messages.assert_awaited_once_with(ROOM_ID)


async def test_start_agent_spawns_agent_module_pane(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start must spawn ``python -m band_wezterm.agent``, not a PoC cat tab."""
    from band_wezterm.identity import HarnessId

    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42

    spawned: list[tuple[object, ...]] = []

    def fake_spawn(window_id: object, cwd: object, command: list[str]) -> PaneId:
        spawned.append((window_id, cwd, command))
        return PaneId(99)

    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.spawn_additional_tab", fake_spawn
    )
    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.set_tab_title", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.preflight_harness", lambda _h: None
    )
    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.write_api_key_file",
        lambda _key: Path("/tmp/band-wezterm-test.key"),
    )

    class _Pane:
        pane_id = 99

    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.list_panes",
        lambda: [_Pane()],
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)
        assert control_app.agents_store.is_running(IDLE_AGENT_ID)
        assert "codex" in (control_app.agents_store.status or "")

    assert len(spawned) == 1
    window_id, _cwd, command = spawned[0]
    assert window_id == 42
    assert "-m" in command and "band_wezterm.agent" in command
    assert "band_a_managed" not in " ".join(command)


async def test_start_agent_requires_managed_key(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from band_wezterm.identity import HarnessId
    from band_wezterm.tui.screens.agents import NO_MANAGED_KEY_MESSAGE

    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = None
    control_app.window_id = 42
    spawn = MagicMock()
    monkeypatch.setattr("band_wezterm.tui.screens.agents.spawn_additional_tab", spawn)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    spawn.assert_not_called()
    assert control_app.agents_store.status == NO_MANAGED_KEY_MESSAGE
