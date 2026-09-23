"""High-value end-to-end behaviors for the disposable Band surfaces."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from band_rest.core.api_error import ApiError
from textual.widgets import Input

from band_wezterm.backends import AgentTuning
from band_wezterm.client import MessageRecord
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import ManagedAgentProfile
from band_wezterm.supervisor import WorkerRecord, WorkerState
from band_wezterm.tui.control_app import ControlApp, InitialAgentAction
from band_wezterm.tui.screens.agents import AgentsScreen
from band_wezterm.tui.screens.register_agent import RegisterAgentScreen
from band_wezterm.tui.screens.rooms import Id as RoomId
from band_wezterm.tui.screens.rooms import RoomDetailScreen
from band_wezterm.tui.screens.rooms import selector as room_selector
from band_wezterm.tui.screens.settings import Id as SettingsId
from band_wezterm.tui.screens.settings import selector as settings_selector
from band_wezterm.tui.screens.sign_in import SignInScreen

from .conftest import agent, participant, room, settle

AGENT_ID = "agent-1"
ROOM_ID = "room-1"


def _profile(agent_id: str, name: str) -> ManagedAgentProfile:
    return ManagedAgentProfile(
        agent_id=agent_id,
        name=name,
        harness=HarnessId.CODEX,
        tuning=AgentTuning(),
    )


def _worker(agent_id: str, name: str) -> WorkerRecord:
    return WorkerRecord(
        agent_id=agent_id,
        name=name,
        pid=1,
        control_socket="/tmp/band-worker.sock",
        control_token="worker-token",
        cwd=str(Path.cwd()),
        started_at=0,
        state=WorkerState.RUNNING,
    )


async def test_signed_in_surface_opens_agents(control_app: ControlApp) -> None:
    async with control_app.run_test() as pilot:
        await settle(pilot)
        assert isinstance(control_app.screen, AgentsScreen)


async def test_direct_agent_create_opens_registration(control_app: ControlApp) -> None:
    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.initial_agent_action = InitialAgentAction.CREATE
        await control_app._open_initial_agent_flow()
        await settle(pilot)
        assert isinstance(control_app.screen, RegisterAgentScreen)


async def test_direct_agent_configure_opens_selected_agent(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    selected = agent(AGENT_ID, "Architect", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [selected]

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.initial_agent_action = InitialAgentAction.CONFIGURE
        control_app.initial_agent_id = selected.id
        await control_app._open_initial_agent_flow()
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)
        assert screen.agent == selected
        assert screen.reconfigure


async def test_start_and_stop_selected_agent_use_detached_worker(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    selected = agent(AGENT_ID, "Architect", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [selected]
    control_app.managed_agents.record(_profile(selected.id, selected.name))
    control_app.supervisor.start.return_value = _worker(selected.id, selected.name)
    control_app.supervisor.stop.return_value = _worker(selected.id, selected.name)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)
        assert control_app.agents_store.is_running(selected.id)
        await pilot.press("x")
        await settle(pilot)

    control_app.supervisor.start.assert_awaited_once()
    control_app.supervisor.stop.assert_awaited_once_with(selected.id)


async def test_room_create_opens_the_new_room(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    created = room(ROOM_ID, "Planning")
    band_client.create_room = AsyncMock(return_value=created)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.action_show_rooms()
        await settle(pilot)
        await pilot.press("n")
        draft = control_app.screen.query_one(room_selector(RoomId.DRAFT_TITLE), Input)
        draft.value = created.title
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(control_app.screen, RoomDetailScreen)
        assert control_app.screen.room == created


async def test_room_roster_can_start_a_managed_participant(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    selected = agent(AGENT_ID, "Architect", harness=HarnessId.CODEX)
    target_room = room(ROOM_ID, "Planning")
    control_app.managed_agents.record(_profile(selected.id, selected.name))
    band_client.list_participants.return_value = [participant(selected)]
    control_app.supervisor.start.return_value = _worker(selected.id, selected.name)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target_room)
        await settle(pilot)
        assert isinstance(control_app.screen, RoomDetailScreen)
        control_app.screen._roster_view().focus()
        await pilot.press("s")
        await settle(pilot)

    control_app.supervisor.start.assert_awaited_once_with(selected.id, cwd=Path.cwd())


async def test_room_loads_message_history(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    target_room = room(ROOM_ID, "Planning")
    message = MessageRecord(
        id="message-1",
        content="Decide the lifecycle.",
        author_name="Architect",
    )
    band_client.list_messages.return_value = [message]

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target_room)
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RoomDetailScreen)
        assert screen.store.messages == [message]


async def test_stale_agent_delete_removes_local_profile(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    selected = agent(AGENT_ID, "Architect", harness=HarnessId.CODEX)
    control_app.managed_agents.record(_profile(selected.id, selected.name))
    band_client.delete_agent.side_effect = ApiError(status_code=404)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.agents_store.add_agent(selected)
        control_app.screen.mutate_reactive(AgentsScreen.store)
        await pilot.press("delete", "delete")
        await settle(pilot)

    assert control_app.managed_agents.get(selected.id) is None


async def test_sign_out_stops_workers_and_returns_to_sign_in(
    control_app: ControlApp, host_auth: MagicMock
) -> None:
    host_auth.sign_out = AsyncMock()

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.action_show_settings()
        await settle(pilot)
        await pilot.click(settings_selector(SettingsId.SIGN_OUT))
        await settle(pilot)
        assert isinstance(control_app.screen, SignInScreen)

    control_app.supervisor.stop_all.assert_awaited_once()
    host_auth.sign_out.assert_awaited_once()
