"""Pilot tests for the Control tab behaviors that are easy to regress."""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from band_rest.core.api_error import ApiError
from textual.widgets import Input, Label, ListView, OptionList, Static

from band_wezterm.agent.adapters import HarnessUnavailableError
from band_wezterm.agent.launch import _spawn_pane
from band_wezterm.agent.native_console import NativeConsoleUnavailableError
from band_wezterm.agent.opencode_server import (
    OpenCodeEndpoint,
    OpenCodeServerError,
)
from band_wezterm.agent_draft import (
    NAME_FORBIDDEN_MESSAGE,
    AgentDraft,
    apply_draft_patch,
)
from band_wezterm.backends import AgentTuning
from band_wezterm.client import (
    MessageRecord,
    ParticipantRecord,
    RealtimeEvent,
    RealtimeEventKind,
    RoomRecord,
)
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import ManagedAgentProfile
from band_wezterm.roles import Role
from band_wezterm.tui.control_app import ControlApp
from band_wezterm.tui.managed_agent_actions import (
    NO_MANAGED_KEY_MESSAGE,
    NO_MANAGED_PROFILE_MESSAGE,
    PANE_CLEANUP_FAILED_MESSAGE,
    PROFILE_HARNESS_UNSTABLE_MESSAGE,
)
from band_wezterm.tui.screens.agents import (
    AgentRow,
    AgentsScreen,
)
from band_wezterm.tui.screens.agents import Id as AgentId
from band_wezterm.tui.screens.agents import selector as agent_selector
from band_wezterm.tui.screens.register_agent import Id as RegisterId
from band_wezterm.tui.screens.register_agent import RegisterAgentScreen, WizardStep
from band_wezterm.tui.screens.register_agent import selector as register_selector
from band_wezterm.tui.screens.rooms import Id as RoomId
from band_wezterm.tui.screens.rooms import (
    IdentityRow,
    RoomDetailScreen,
    RoomRow,
    RoomsScreen,
)
from band_wezterm.tui.screens.rooms import selector as room_selector
from band_wezterm.tui.screens.settings import SettingsScreen
from band_wezterm.tui.screens.sign_in import SignInScreen
from band_wezterm.tui.screens.workspace import (
    AGENT_ACTION_SELECTION_MESSAGE,
    WorkspaceScreen,
)
from band_wezterm.tui.stores import AgentPanes
from band_wezterm.tui.widgets import MarkdownComposer
from band_wezterm.wezterm_cli import PaneId

from .conftest import agent, participant, room, settle

RUNNING_AGENT_ID = "0f5d0b7c-1a3e-4c5b-9d2f-6a7b8c9d0e1f"
IDLE_AGENT_ID = "3c2b1a09-8f7e-4d6c-5b4a-3928176054f3"
ROOM_ID = "9a8b7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d"
AGENT_PANE = PaneId(11)
PROFILE_RECORD_FAILURE_MESSAGE = "disk full"
UX_ROLE = Role(
    id="ux-ui-product-designer",
    label="UX/UI Product Designer",
    content="# UX/UI Product Designer\nDesign simply.\n",
)


def register_status(screen: RegisterAgentScreen) -> str:
    return str(
        screen.query_one(register_selector(RegisterId.STATUS), Static).render()
    )


def highlighted_option_id(screen: RegisterAgentScreen) -> str | None:
    options = screen.query_one(register_selector(RegisterId.OPTIONS), OptionList)
    index = options.highlighted
    if index is None:
        return None
    return options.get_option_at_index(index).id


@pytest.fixture(autouse=True)
def native_console_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep UI tests independent of locally installed harness executables."""
    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.preflight_managed_agent",
        lambda _harness: None,
    )
    monkeypatch.setattr(
        "band_wezterm.tui.screens.register_agent.preflight_managed_agent",
        lambda _harness: None,
    )


def listed_agents(app: ControlApp) -> list[str]:
    return [row.agent.name for row in app.screen.query(AgentRow)]


def listed_rooms(app: ControlApp) -> list[str]:
    return [row.room.title for row in app.screen.query(RoomRow)]


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


async def test_workspace_projects_agents_and_rooms_from_shared_stores(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    band_client.list_my_agents.return_value = [agent(IDLE_AGENT_ID, "Alpha")]
    first_room = room(ROOM_ID, "Planning")
    second_room = room("room-2", "Delivery")
    band_client.list_my_chats.return_value = [first_room, second_room]

    async with control_app.run_test() as pilot:
        await settle(pilot)

        assert isinstance(control_app.screen, WorkspaceScreen)
        assert listed_agents(control_app) == ["Alpha"]
        assert listed_rooms(control_app) == ["Planning", "Delivery"]
        assert control_app.agents_store.selected_id == IDLE_AGENT_ID
        assert control_app.rooms_store.selected_id == ROOM_ID


async def test_workspace_refresh_reconciles_removed_room_selection(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    selected_room = room(ROOM_ID, "Planning")
    replacement_room = room("room-2", "Delivery")
    band_client.list_my_chats.return_value = [selected_room, replacement_room]

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.rooms_store.selected_id = selected_room.id
        band_client.list_my_chats.return_value = [replacement_room]

        await pilot.press("r")
        await settle(pilot)

        assert listed_rooms(control_app) == ["Delivery"]
        assert control_app.rooms_store.selected_id == replacement_room.id


async def test_workspace_opens_selected_room(control_app: ControlApp, band_client: MagicMock) -> None:
    selected_room = room(ROOM_ID, "Planning")
    band_client.list_my_chats.return_value = [selected_room]

    async with control_app.run_test() as pilot:
        await settle(pilot)
        rooms = control_app.screen.query_one(room_selector(RoomId.LIST), ListView)
        rooms.focus()

        await pilot.press("enter")
        await settle(pilot)

        assert isinstance(control_app.screen, RoomDetailScreen)
        assert control_app.rooms_store.selected_id == selected_room.id


async def test_workspace_room_focus_cannot_apply_agent_action(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    band_client.list_my_agents.return_value = [agent(IDLE_AGENT_ID, "Alpha")]
    band_client.list_my_chats.return_value = [room(ROOM_ID, "Planning")]

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.screen.query_one(room_selector(RoomId.LIST), ListView).focus()

        await pilot.press("s")
        await settle(pilot)

        assert control_app.agents_store.starting_ids == set()
        assert control_app.rooms_store.status == AGENT_ACTION_SELECTION_MESSAGE


async def test_register_opens_wizard_and_escape_returns(
    control_app: ControlApp,
) -> None:
    """Register pushes the multi-step wizard; Esc returns to Agents."""
    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        assert isinstance(control_app.screen, RegisterAgentScreen)

        await pilot.press("escape")
        await settle(pilot)
        assert isinstance(control_app.screen, AgentsScreen)


async def test_register_records_role_model_and_effort(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "band_wezterm.tui.screens.register_agent.list_roles",
        lambda: [UX_ROLE],
    )
    band_client.create_agent.return_value = agent(IDLE_AGENT_ID, "Created")

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)

        await pilot.press("down", "enter")
        await settle(pilot)
        assert screen.step is WizardStep.ROLE

        await pilot.press("down", "enter")
        await settle(pilot)
        assert screen.step is WizardStep.NAME
        assert "/" not in screen.query_one(
            register_selector(RegisterId.TEXT), Input
        ).value

        await pilot.press("enter")
        await settle(pilot)
        assert screen.step is WizardStep.DESCRIPTION

        await pilot.press("enter")
        await settle(pilot)
        assert screen.step is WizardStep.MODEL

        await pilot.press("down", "enter")
        await settle(pilot)
        assert screen.step is WizardStep.REASONING
        await pilot.press("down", "down", "enter")
        await settle(pilot)
        assert isinstance(control_app.screen, AgentsScreen)

    band_client.create_agent.assert_awaited_once()
    registered_name = band_client.create_agent.await_args.kwargs["name"]
    assert "/" not in registered_name
    assert "@" not in registered_name
    stored = control_app.managed_agents.get(IDLE_AGENT_ID)
    assert stored is not None
    assert stored.harness is HarnessId.CODEX
    assert stored.persona == UX_ROLE.content
    assert stored.tuning.model == "gpt-5.6-sol"
    assert stored.tuning.reasoning == "medium"


async def test_register_rejects_forbidden_name_before_the_platform(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "band_wezterm.tui.screens.register_agent.list_roles",
        list,
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)

        await pilot.press("enter")
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        assert screen.step is WizardStep.NAME

        name_input = screen.query_one(register_selector(RegisterId.TEXT), Input)
        name_input.value = "bad/name"
        await name_input.action_submit()
        await settle(pilot)

        assert screen.step is WizardStep.NAME
        assert NAME_FORBIDDEN_MESSAGE in register_status(screen)

    band_client.create_agent.assert_not_called()


async def test_register_submit_returns_to_name_when_draft_name_is_illegal(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)
        screen.draft = AgentDraft(
            harness=HarnessId.CODEX,
            name="UX/UI",
            description="Registered for name validation coverage.",
        )
        screen.step = WizardStep.REASONING
        screen._submit()
        await settle(pilot)
        assert screen.step is WizardStep.NAME
        assert NAME_FORBIDDEN_MESSAGE in register_status(screen)

    band_client.create_agent.assert_not_called()



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


async def test_two_running_agents_can_create_a_room_and_receive_mentions(
    control_app: ControlApp, band_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The Control journey keeps roster, mentions, and both runtime states aligned."""
    first = agent(RUNNING_AGENT_ID, "Alpha", harness=HarnessId.CODEX)
    second = agent(IDLE_AGENT_ID, "Developer 6753", harness=HarnessId.CLAUDE)
    created_room = room(ROOM_ID, "Pair review")
    participants: list[ParticipantRecord] = []
    sent: list[tuple[str, str, str]] = []

    async def add_participant(_room_id: str, participant_id: str) -> None:
        record = next(item for item in (first, second) if item.id == participant_id)
        participants.append(
            ParticipantRecord(
                id=record.id,
                name=record.name,
                handle=record.name,
                kind=record.kind,
                color=record.color,
            )
        )

    async def send_message(
        room_id: str, body: str, *, mention_id: str, mention_name: str
    ) -> MessageRecord:
        sent.append((room_id, body, mention_id))
        return MessageRecord(
            id=f"message-{len(sent)}", content=body, author_name=mention_name
        )

    band_client.list_my_agents.return_value = [first, second]
    band_client.create_room.return_value = created_room
    band_client.list_participants.side_effect = lambda _room_id: list(participants)
    band_client.add_participant.side_effect = add_participant
    band_client.send_message.side_effect = send_message
    monkeypatch.setattr("band_wezterm.tui.control_app.kill_panes", lambda _panes: None)
    control_app.agents_store.mark_running(first.id, PaneId(11), console=PaneId(10))
    control_app.agents_store.mark_running(second.id, PaneId(13), console=PaneId(12))

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("ctrl+o", "n")
        title = control_app.screen.query_one(room_selector(RoomId.DRAFT_TITLE), Input)
        title.value = created_room.title
        await title.action_submit()
        await settle(pilot)
        assert isinstance(control_app.screen, RoomDetailScreen)

        await pilot.press("a", "enter")
        await settle(pilot)
        await pilot.press("a", "enter")
        await settle(pilot)
        assert [item.name for item in control_app.rooms_store.participants] == [
            "Alpha",
            "Developer 6753",
        ]

        composer = control_app.screen.query_one(
            room_selector(RoomId.COMPOSER), MarkdownComposer
        )
        assert tuple(composer._mention_handles) == ("Alpha", "Developer 6753")
        composer.value = "@Alpha inspect the plan"
        await composer.action_submit()
        await settle(pilot)
        composer.value = "@Developer 6753 review the implementation"
        await composer.action_submit()
        await settle(pilot)

    assert sent == [
        (ROOM_ID, "inspect the plan", RUNNING_AGENT_ID),
        (ROOM_ID, "review the implementation", IDLE_AGENT_ID),
    ]


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


async def test_rejected_jwt_returns_to_sign_in_once(
    control_app: ControlApp, band_client: MagicMock, host_auth: MagicMock
) -> None:
    async with control_app.run_test() as pilot:
        await settle(pilot)
        rejected = band_client.set_authentication_rejected_handler.call_args.args[0]
        rejected()
        rejected()
        await settle(pilot)
        assert isinstance(control_app.screen, SignInScreen)
        host_auth.sign_out.assert_awaited_once()


async def test_unmount_stops_every_agent_tab_the_host_started(
    control_app: ControlApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    killed: list[PaneId] = []
    monkeypatch.setattr(
        "band_wezterm.tui.control_app.kill_panes",
        killed.extend,
    )
    control_app.agents_store.mark_running(
        RUNNING_AGENT_ID,
        AGENT_PANE,
        console=PaneId(10),
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)

    assert killed == [PaneId(10), AGENT_PANE]
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

    band_client.list_messages.assert_awaited_once_with(
        ROOM_ID, limit=control_app.preferences.current.chat_messages_limit
    )


async def test_candidate_load_failure_is_not_shown_as_an_empty_directory(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    failure = "directory unavailable"
    band_client.list_my_agents.side_effect = RuntimeError(failure)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(room(ROOM_ID, "Core"))
        await settle(pilot)
        await pilot.press("a")
        await settle(pilot)
        status = control_app.screen.query_one(
            room_selector(RoomId.DETAIL_STATUS), Static
        )
        assert str(status.render()) == failure


async def test_room_roster_shows_local_agent_runtime(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    member = agent(RUNNING_AGENT_ID, "Alpha")
    band_client.list_participants.return_value = [participant(member)]
    control_app.agents_store.mark_running(RUNNING_AGENT_ID, AGENT_PANE)
    target = room(ROOM_ID, "Core")

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target)
        await settle(pilot)

        row = control_app.screen.query_one(IdentityRow)
        assert [str(label.render()) for label in row.query(Label)] == ["Alpha"]
        indicator = row.query_one(".row-runtime", Static)
        assert str(indicator.render()) == "●"


async def test_room_roster_starts_selected_managed_agent(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_participants.return_value = [participant(member)]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    control_app.managed_agents.record(
        ManagedAgentProfile(agent_id=IDLE_AGENT_ID, name="Beta", harness=HarnessId.CODEX)
    )
    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.prepare_agent_launch",
        lambda _context, **_kwargs: object(),
    )

    async def spawn(_context: object, _resources: object) -> AgentPanes:
        return AgentPanes(console=PaneId(99), bridge=PaneId(100))

    monkeypatch.setattr("band_wezterm.tui.managed_agent_actions.spawn_agent_panes", spawn)
    target = room(ROOM_ID, "Core")

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target)
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    assert control_app.agents_store.is_running(IDLE_AGENT_ID)
    assert "Started Beta" in control_app.rooms_store.status


async def test_room_roster_stops_selected_managed_agent(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member = agent(RUNNING_AGENT_ID, "Alpha")
    band_client.list_participants.return_value = [participant(member)]
    control_app.agents_store.mark_running(
        RUNNING_AGENT_ID, bridge=PaneId(100), console=PaneId(99)
    )
    stopped: list[tuple[PaneId, ...]] = []

    def kill(panes: tuple[PaneId, ...]) -> None:
        stopped.append(panes)

    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.kill_panes",
        kill,
    )
    target = room(ROOM_ID, "Core")

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target)
        await settle(pilot)
        await pilot.press("t")
        await settle(pilot)

    assert stopped == [(PaneId(99), PaneId(100))]
    assert not control_app.agents_store.is_running(RUNNING_AGENT_ID)
    assert control_app.rooms_store.status == "Stopped Alpha."


async def test_start_agent_spawns_private_console_and_band_bridge(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CLAUDE_SDK)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    control_app.managed_agents.record(
        ManagedAgentProfile(
            agent_id=IDLE_AGENT_ID,
            name="Beta",
            harness=HarnessId.CODEX,
            tuning=AgentTuning(model="o3", reasoning="high"),
        )
    )

    spawned: list[tuple[object, ...]] = []
    split: list[tuple[object, ...]] = []
    activated: list[PaneId] = []
    preflighted: list[object] = []

    def fake_spawn(window_id: object, cwd: object, command: list[str]) -> PaneId:
        spawned.append((window_id, cwd, command))
        return PaneId(99)

    def fake_split(pane_id: PaneId, cwd: Path, command: list[str]) -> PaneId:
        split.append((pane_id, cwd, command))
        return PaneId(100)

    monkeypatch.setattr(
        "band_wezterm.agent.launch.spawn_additional_tab", fake_spawn
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.set_tab_title", lambda *_a, **_k: None
    )
    monkeypatch.setattr("band_wezterm.agent.launch.split_pane", fake_split)
    monkeypatch.setattr(
        "band_wezterm.agent.launch.activate_pane", activated.append
    )
    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.preflight_managed_agent",
        preflighted.append,
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.write_api_key_file",
        lambda _key: Path("/tmp/band-wezterm-test.key"),
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.write_native_console_launch",
        lambda _launch: tmp_path / "console.json",
    )

    class _Pane:
        def __init__(self, pane_id: int) -> None:
            self.pane_id = pane_id

    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.list_panes",
        lambda: [_Pane(99), _Pane(100)],
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        # Load-path projection — before Start's own sync can mask a miss.
        assert control_app.agents_store.find(IDLE_AGENT_ID).harness is HarnessId.CODEX
        await pilot.press("s")
        await settle(pilot)
        assert control_app.agents_store.is_running(IDLE_AGENT_ID)
        assert HarnessId.CODEX.value in (control_app.agents_store.status or "")
        assert control_app.agents_store.running[IDLE_AGENT_ID].console == PaneId(99)
        assert control_app.agents_store.running[IDLE_AGENT_ID].bridge == PaneId(100)

    assert len(spawned) == 1
    window_id, _cwd, console_command = spawned[0]
    assert window_id == 42
    assert "band_wezterm.agent.console" in console_command
    assert "band_a_managed" not in " ".join(console_command)
    assert console_command[console_command.index("--harness") + 1] == (
        HarnessId.CODEX.value
    )
    assert len(split) == 1
    console_pane, _cwd, bridge_command = split[0]
    assert console_pane == PaneId(99)
    assert "band_wezterm.agent" in bridge_command
    assert "band_wezterm.agent.console" not in bridge_command
    assert "--model" in bridge_command
    assert "o3" in bridge_command
    assert "--reasoning" in bridge_command
    assert "high" in bridge_command
    assert bridge_command[bridge_command.index("--harness") + 1] == (
        HarnessId.CODEX.value
    )
    assert activated == [PaneId(99)]
    assert preflighted == [HarnessId.CODEX]
    assert control_app.agents_store.find(IDLE_AGENT_ID).harness is HarnessId.CODEX


async def test_start_agent_surfaces_missing_native_console_before_spawning(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    control_app.managed_agents.record(
        ManagedAgentProfile(agent_id=IDLE_AGENT_ID, name="Beta", harness=HarnessId.CODEX)
    )
    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.preflight_managed_agent",
        lambda _harness: (_ for _ in ()).throw(NativeConsoleUnavailableError("codex CLI not found")),
    )
    spawned = MagicMock()
    monkeypatch.setattr("band_wezterm.agent.launch.spawn_additional_tab", spawned)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    spawned.assert_not_called()
    assert control_app.agents_store.status == "codex CLI not found"


async def test_start_opencode_agent_provisions_server_before_launch(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.OPENCODE)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    control_app.managed_agents.record(
        ManagedAgentProfile(
            agent_id=IDLE_AGENT_ID,
            name="Beta",
            harness=HarnessId.OPENCODE,
        )
    )
    endpoint = OpenCodeEndpoint("http://127.0.0.1:43117")
    ensure = AsyncMock(return_value=endpoint)
    monkeypatch.setattr(control_app.opencode_server, "ensure", ensure)
    captured: list[OpenCodeEndpoint | None] = []

    def prepare(
        _context: object, *, opencode_endpoint: OpenCodeEndpoint | None
    ) -> object:
        captured.append(opencode_endpoint)
        return object()

    async def spawn(_context: object, _resources: object) -> AgentPanes:
        return AgentPanes(console=PaneId(99), bridge=PaneId(100))

    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.prepare_agent_launch", prepare
    )
    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.spawn_agent_panes", spawn
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    assert captured == [endpoint]
    ensure.assert_awaited_once()
    assert control_app.agents_store.is_running(IDLE_AGENT_ID)


async def test_start_opencode_agent_surfaces_server_failure_without_panes(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.OPENCODE)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    control_app.managed_agents.record(
        ManagedAgentProfile(
            agent_id=IDLE_AGENT_ID,
            name="Beta",
            harness=HarnessId.OPENCODE,
        )
    )
    ensure = AsyncMock(
        side_effect=OpenCodeServerError("OpenCode server failed to start.")
    )
    monkeypatch.setattr(control_app.opencode_server, "ensure", ensure)
    prepare = MagicMock()
    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.prepare_agent_launch", prepare
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    prepare.assert_not_called()
    assert control_app.agents_store.status == "OpenCode server failed to start."


async def test_cancelled_pane_spawn_retains_pane_for_transaction_cleanup() -> None:
    started = threading.Event()
    release = threading.Event()
    acquired: list[PaneId] = []

    def create() -> PaneId:
        started.set()
        release.wait()
        return PaneId(99)

    task = asyncio.create_task(_spawn_pane(create, acquired))
    await asyncio.to_thread(started.wait)
    task.cancel()
    release.set()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert acquired == [PaneId(99)]


async def test_failed_start_retains_pane_ownership_when_cleanup_fails(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    control_app.managed_agents.record(
        ManagedAgentProfile(agent_id=IDLE_AGENT_ID, name="Beta", harness=HarnessId.CODEX)
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.spawn_additional_tab",
        lambda *_args: PaneId(99),
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.set_tab_title",
        lambda *_args: (_ for _ in ()).throw(OSError("title unavailable")),
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.kill_panes",
        lambda _panes: (_ for _ in ()).throw(OSError("mux unavailable")),
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.write_api_key_file",
        lambda _key: tmp_path / "agent.key",
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.write_native_console_launch",
        lambda _launch: tmp_path / "console.json",
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    panes = control_app.agents_store.running[IDLE_AGENT_ID]
    assert panes.ids == (PaneId(99),)
    assert control_app.agents_store.status == PANE_CLEANUP_FAILED_MESSAGE


async def test_start_agent_repreflights_through_chained_midflight_reconfigure(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A→B→C mid-flight must preflight C before spawn — not only B."""
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CLAUDE)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    control_app.managed_agents.record(
        ManagedAgentProfile(
            agent_id=IDLE_AGENT_ID,
            name="Beta",
            harness=HarnessId.CODEX,
        )
    )

    spawned: list[list[str]] = []
    preflighted: list[object] = []
    midflight_harness: dict[HarnessId, HarnessId] = {
        HarnessId.CODEX: HarnessId.COPILOT,
        HarnessId.COPILOT: HarnessId.CLAUDE,
    }

    def fake_preflight(harness: object) -> None:
        preflighted.append(harness)
        if not isinstance(harness, HarnessId):
            return
        next_harness = midflight_harness.get(harness)
        if next_harness is None:
            return
        current = control_app.managed_agents.get(IDLE_AGENT_ID)
        assert current is not None
        control_app.managed_agents.record(
            current.model_copy(update={"harness": next_harness})
        )

    def fake_spawn(window_id: object, cwd: object, command: list[str]) -> PaneId:
        spawned.append(command)
        return PaneId(99)

    monkeypatch.setattr(
        "band_wezterm.agent.launch.spawn_additional_tab", fake_spawn
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.set_tab_title", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.split_pane",
        lambda _pane, _cwd, _command: PaneId(100),
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.activate_pane", lambda _pane: None
    )
    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.preflight_managed_agent",
        fake_preflight,
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.write_api_key_file",
        lambda _key: Path("/tmp/band-wezterm-test.key"),
    )
    monkeypatch.setattr(
        "band_wezterm.agent.launch.write_native_console_launch",
        lambda _launch: tmp_path / "console.json",
    )

    class _Pane:
        def __init__(self, pane_id: int) -> None:
            self.pane_id = pane_id

    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.list_panes",
        lambda: [_Pane(99), _Pane(100)],
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)
        assert control_app.agents_store.is_running(IDLE_AGENT_ID)

    assert preflighted == [HarnessId.CODEX, HarnessId.COPILOT, HarnessId.CLAUDE]
    assert len(spawned) == 1
    assert spawned[0][spawned[0].index("--harness") + 1] == HarnessId.CLAUDE.value
    assert control_app.agents_store.find(IDLE_AGENT_ID).harness is HarnessId.CLAUDE


async def test_start_agent_requires_managed_key(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = None
    control_app.window_id = 42
    spawn = MagicMock()
    monkeypatch.setattr("band_wezterm.agent.launch.spawn_additional_tab", spawn)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    spawn.assert_not_called()
    assert control_app.agents_store.status == NO_MANAGED_KEY_MESSAGE


async def test_start_agent_requires_managed_profile(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    spawn = MagicMock()
    monkeypatch.setattr("band_wezterm.agent.launch.spawn_additional_tab", spawn)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    spawn.assert_not_called()
    assert control_app.agents_store.status == NO_MANAGED_PROFILE_MESSAGE


async def test_sign_out_returns_to_sign_in(
    control_app: ControlApp, host_auth: MagicMock
) -> None:
    """Ctrl+L clears the session and shows Sign In."""
    host_auth.sign_out = AsyncMock()

    async with control_app.run_test() as pilot:
        await settle(pilot)
        assert isinstance(control_app.screen, AgentsScreen)
        await pilot.press("ctrl+l")
        await settle(pilot)
        assert isinstance(control_app.screen, SignInScreen)
        assert control_app.user_id is None
    host_auth.sign_out.assert_awaited_once()


async def test_sign_out_reaches_sign_in_when_agent_teardown_fails(
    control_app: ControlApp,
    host_auth: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    control_app.agents_store.mark_running(
        RUNNING_AGENT_ID,
        PaneId(12),
        console=PaneId(11),
    )
    monkeypatch.setattr(
        "band_wezterm.tui.control_app.kill_panes",
        lambda _panes: (_ for _ in ()).throw(OSError("mux unavailable")),
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("ctrl+l")
        await settle(pilot)
        assert isinstance(control_app.screen, SignInScreen)

    host_auth.sign_out.assert_awaited_once()
    assert control_app.agents_store.running == {}


async def test_workspace_failure_after_browser_sign_in_is_retryable(
    control_app: ControlApp,
    band_client: MagicMock,
    host_auth: MagicMock,
) -> None:
    host_auth.has_stored_tokens.return_value = False
    band_client.whoami.side_effect = RuntimeError("platform unavailable")

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, SignInScreen)
        assert not screen.busy
        assert "platform unavailable" in screen.status

    host_auth.sign_in.assert_awaited_once()


async def test_realtime_roster_change_refreshes_participants(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    first = agent(RUNNING_AGENT_ID, "Alpha")
    second = agent(IDLE_AGENT_ID, "Beta")
    band_client.list_participants.side_effect = [[participant(first)], [participant(first), participant(second)]]
    target = room(ROOM_ID, "Core")

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target)
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RoomDetailScreen)
        screen.on_room_detail_screen_incoming(
            RoomDetailScreen.Incoming(
                RealtimeEvent(kind=RealtimeEventKind.PARTICIPANT_JOINED, room_id=ROOM_ID)
            )
        )
        await settle(pilot)
        assert [row.identity.name for row in screen.query(IdentityRow)] == ["Alpha", "Beta"]


async def test_room_reload_replaces_its_realtime_listener(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    released: list[int] = []

    def subscribe(_callback: object) -> object:
        index = band_client.subscribe_realtime.call_count - 1
        return lambda: released.append(index)

    band_client.subscribe_realtime.side_effect = subscribe
    band_client.list_participants.return_value = []
    band_client.list_messages.return_value = []
    target = room(ROOM_ID, "Core")

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target)
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RoomDetailScreen)
        screen.action_reload()
        await settle(pilot)
        assert released == [0]

    assert released == [0, 1]


async def test_failed_send_keeps_composer_draft_for_retry(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    target = room(ROOM_ID, "Core")
    recipient = agent(IDLE_AGENT_ID, "Developer 6753")
    band_client.list_participants.return_value = [participant(recipient)]
    band_client.send_message.side_effect = RuntimeError("network unavailable")
    draft = "@Developer 6753 review this"

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target)
        await settle(pilot)
        composer = control_app.screen.query_one(
            room_selector(RoomId.COMPOSER), Input
        )
        composer.value = draft
        await composer.action_submit()
        await settle(pilot)
        assert composer.value == draft
        assert "network unavailable" in control_app.rooms_store.status


async def test_escape_cancels_pending_browser_sign_in(
    control_app: ControlApp, host_auth: MagicMock
) -> None:
    host_auth.has_stored_tokens.return_value = False
    pending = asyncio.Event()

    async def wait_for_browser() -> None:
        await pending.wait()

    host_auth.sign_in.side_effect = wait_for_browser
    host_auth.cancel_sign_in.side_effect = pending.set

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("enter", "escape")
        await settle(pilot)
        assert isinstance(control_app.screen, AgentsScreen)

    host_auth.cancel_sign_in.assert_called_once()


async def test_global_navigation_reaches_every_base_screen(
    control_app: ControlApp,
) -> None:
    async with control_app.run_test() as pilot:
        await settle(pilot)
        assert isinstance(control_app.screen, AgentsScreen)

        await pilot.press("ctrl+o")
        await settle(pilot)
        assert isinstance(control_app.screen, RoomsScreen)

        await pilot.press("ctrl+comma")
        await settle(pilot)
        assert isinstance(control_app.screen, SettingsScreen)

        await pilot.press("escape")
        await settle(pilot)
        assert isinstance(control_app.screen, RoomsScreen)

        await pilot.press("ctrl+a")
        await settle(pilot)
        assert isinstance(control_app.screen, AgentsScreen)


async def test_reconfigure_opens_wizard(control_app: ControlApp, band_client: MagicMock) -> None:
    band_client.list_my_agents.return_value = [
        agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX),
    ]
    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("c")
        await settle(pilot)
        assert isinstance(control_app.screen, RegisterAgentScreen)
        assert control_app.screen.reconfigure is True


async def test_reconfigure_records_profile_as_the_runtime_source_of_truth(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    control_app.managed_agents.record(
        ManagedAgentProfile(
            agent_id=IDLE_AGENT_ID,
            name="Beta",
            harness=HarnessId.CODEX,
            tuning=AgentTuning(reasoning="high"),
        )
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("c")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)
        screen.draft = apply_draft_patch(screen.draft, harness=HarnessId.COPILOT_SDK)
        screen._submit_reconfigure()
        await settle(pilot)
        assert isinstance(control_app.screen, AgentsScreen)

    stored = control_app.managed_agents.get(IDLE_AGENT_ID)
    assert stored is not None
    assert stored.harness is HarnessId.COPILOT_SDK
    assert control_app.agents_store.find(IDLE_AGENT_ID).harness is HarnessId.COPILOT_SDK
    assert "Reconfigured Beta" in (control_app.agents_store.status or "")


async def test_reconfigure_completes_through_the_keyboard_wizard(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    control_app.managed_agents.record(
        ManagedAgentProfile(
            agent_id=IDLE_AGENT_ID,
            name="Beta",
            harness=HarnessId.CODEX,
            persona="# Existing role\n",
            tuning=AgentTuning(reasoning="low"),
        )
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("c")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)
        assert screen.step.value == "harness"
        assert highlighted_option_id(screen) == HarnessId.CODEX.value

        await pilot.press("enter")
        await settle(pilot)
        assert screen.step.value == "role"

        await pilot.press("enter")
        await settle(pilot)
        assert screen.step.value == "model"

        await pilot.press("enter")
        await settle(pilot)
        assert screen.step.value == "reasoning"
        assert highlighted_option_id(screen) == "low"

        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(control_app.screen, AgentsScreen)

    stored = control_app.managed_agents.get(IDLE_AGENT_ID)
    assert stored is not None
    assert stored.harness is HarnessId.CODEX
    assert stored.persona == "# Existing role\n"
    assert stored.tuning.reasoning == "low"


async def test_reconfigure_aborts_when_profile_record_fails(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    previous = ManagedAgentProfile(
        agent_id=IDLE_AGENT_ID,
        name="Beta",
        harness=HarnessId.CODEX,
        tuning=AgentTuning(reasoning="high"),
    )
    control_app.managed_agents.record(previous)

    def boom() -> None:
        raise OSError(PROFILE_RECORD_FAILURE_MESSAGE)

    monkeypatch.setattr(control_app.managed_agents, "_save", boom)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("c")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)
        screen.draft = apply_draft_patch(screen.draft, harness=HarnessId.COPILOT_SDK)
        screen._submit_reconfigure()
        await settle(pilot)
        assert isinstance(control_app.screen, RegisterAgentScreen)
        assert PROFILE_RECORD_FAILURE_MESSAGE in str(
            screen.query_one(register_selector(RegisterId.STATUS), Static).render()
        )

    assert control_app.managed_agents.get(IDLE_AGENT_ID) == previous
    assert control_app.agents_store.find(IDLE_AGENT_ID).harness is HarnessId.CODEX


async def test_register_deletes_agent_when_profile_record_fails(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.create_agent.return_value = created

    def boom() -> None:
        raise OSError(PROFILE_RECORD_FAILURE_MESSAGE)

    monkeypatch.setattr(control_app.managed_agents, "_save", boom)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)
        screen.draft = AgentDraft(
            harness=HarnessId.CODEX,
            name="Beta",
            description="Registered for profile rollback coverage.",
        )
        screen._submit()
        await settle(pilot)
        assert isinstance(control_app.screen, RegisterAgentScreen)
        assert PROFILE_RECORD_FAILURE_MESSAGE in str(
            screen.query_one(register_selector(RegisterId.STATUS), Static).render()
        )

    band_client.create_agent.assert_awaited_once()
    band_client.delete_agent.assert_awaited_once_with(IDLE_AGENT_ID)
    assert control_app.agents_store.find(IDLE_AGENT_ID) is None
    assert control_app.managed_agents.get(IDLE_AGENT_ID) is None


async def test_register_rejects_an_unavailable_harness_before_creating_agent(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unavailable = "Native opencode CLI is unavailable"
    monkeypatch.setattr(
        "band_wezterm.tui.screens.register_agent.preflight_managed_agent",
        lambda _harness: (_ for _ in ()).throw(NativeConsoleUnavailableError(unavailable)),
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)
        screen.draft = AgentDraft(
            harness=HarnessId.OPENCODE,
            name="OpenCode",
            description="A local OpenCode assistant.",
        )
        screen._submit()
        await settle(pilot)
        assert register_status(screen) == unavailable

    band_client.create_agent.assert_not_awaited()


async def test_delete_requires_confirmation(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[PaneId] = []
    band_client.list_my_agents.return_value = [
        agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX),
    ]
    control_app.agents_store.mark_running(
        IDLE_AGENT_ID,
        PaneId(100),
        console=PaneId(99),
    )
    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.kill_panes",
        killed.extend,
    )
    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("delete")
        await settle(pilot)
        assert "Press Delete again" in (control_app.agents_store.status or "")
        band_client.delete_agent.assert_not_called()
        await pilot.press("delete")
        await settle(pilot)
        band_client.delete_agent.assert_awaited()
        assert band_client.delete_agent.await_args.args[0] == IDLE_AGENT_ID

    assert killed == [PaneId(99), PaneId(100)]
    assert not control_app.agents_store.is_running(IDLE_AGENT_ID)


async def test_delete_surfaces_in_progress_state(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    pending = asyncio.Event()
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]

    async def delete_when_released(_: str) -> None:
        await pending.wait()

    band_client.delete_agent.side_effect = delete_when_released

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("delete", "delete")
        await pilot.pause()

        assert control_app.agents_store.is_deleting(target.id)
        assert control_app.agents_store.status == "Deleting Beta…"

        pending.set()
        await settle(pilot)

    assert control_app.agents_store.find(target.id) is None


async def test_delete_reconciles_an_agent_already_missing_remotely(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = []
    band_client.delete_agent.side_effect = ApiError(status_code=404)
    control_app.managed_agents.record(
        ManagedAgentProfile(agent_id=target.id, name=target.name, harness=HarnessId.CODEX)
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.agents_store.add_agent(target)
        control_app.screen.mutate_reactive(AgentsScreen.store)
        await settle(pilot)
        await pilot.press("delete", "delete")
        await settle(pilot)

    assert control_app.agents_store.find(target.id) is None
    assert control_app.managed_agents.get(target.id) is None
    assert "already deleted remotely" in (control_app.agents_store.status or "")


async def test_reload_reports_completion_and_refreshes_both_catalogs(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    band_client.list_directory.return_value = [target]

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("r")
        await settle(pilot)

        assert control_app.agents_store.status == "Refreshed 1 agents."

        await pilot.press("d")
        await settle(pilot)
        assert control_app.agents_store.source.value == "directory"
        assert control_app.agents_store.status == "Refreshed 1 public agents."

        await pilot.press("d")
        await settle(pilot)

    assert band_client.list_my_agents.await_count == 3



async def test_delete_room_requires_confirmation(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    """Delete on the rooms list is two-press, matching agents."""
    target = room(ROOM_ID, "Core")
    deleted = False

    async def list_rooms() -> list[RoomRecord]:
        return [] if deleted else [target]

    async def delete_room(_room_id: str) -> None:
        nonlocal deleted
        deleted = True

    band_client.list_my_chats.side_effect = list_rooms
    band_client.delete_room.side_effect = delete_room

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("ctrl+o")
        await settle(pilot)
        assert isinstance(control_app.screen, RoomsScreen)
        await pilot.press("delete")
        await settle(pilot)
        assert "Press Delete again" in (control_app.rooms_store.status or "")
        band_client.delete_room.assert_not_called()
        await pilot.press("delete")
        await settle(pilot)
        band_client.delete_room.assert_awaited()
        assert band_client.delete_room.await_args.args[0] == ROOM_ID
        assert control_app.rooms_store.find(ROOM_ID) is None


async def test_delete_room_from_detail_returns_to_list(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    target = room(ROOM_ID, "Core")
    deleted = False

    async def list_rooms() -> list[RoomRecord]:
        return [] if deleted else [target]

    async def delete_room(_room_id: str) -> None:
        nonlocal deleted
        deleted = True

    band_client.list_my_chats.side_effect = list_rooms
    band_client.delete_room.side_effect = delete_room
    band_client.list_participants.return_value = []

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("ctrl+o")
        await settle(pilot)
        assert isinstance(control_app.screen, RoomsScreen)
        await pilot.press("enter")
        await settle(pilot)
        assert isinstance(control_app.screen, RoomDetailScreen)
        await pilot.press("delete")
        await settle(pilot)
        band_client.delete_room.assert_not_called()
        await pilot.press("delete")
        await settle(pilot)
        band_client.delete_room.assert_awaited()
        assert isinstance(control_app.screen, RoomsScreen)
        assert control_app.rooms_store.find(ROOM_ID) is None

async def test_register_surfaces_cleanup_failure_when_delete_fails(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.create_agent.return_value = created
    cleanup_message = "delete refused"

    def boom() -> None:
        raise OSError(PROFILE_RECORD_FAILURE_MESSAGE)

    monkeypatch.setattr(control_app.managed_agents, "_save", boom)
    band_client.delete_agent.side_effect = RuntimeError(cleanup_message)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)
        screen.draft = AgentDraft(
            harness=HarnessId.CODEX,
            name="Beta",
            description="Registered for cleanup failure coverage.",
        )
        screen._submit()
        await settle(pilot)
        status = str(
            screen.query_one(register_selector(RegisterId.STATUS), Static).render()
        )
        assert PROFILE_RECORD_FAILURE_MESSAGE in status
        assert cleanup_message in status
        assert "cleanup failed" in status

    band_client.delete_agent.assert_awaited_once_with(IDLE_AGENT_ID)


async def test_start_agent_surfaces_harness_unavailable(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    control_app.managed_agents.record(
        ManagedAgentProfile(
            agent_id=IDLE_AGENT_ID,
            name="Beta",
            harness=HarnessId.CODEX,
        )
    )
    unavailable = "uv sync --extra codex"
    spawn = MagicMock()

    def boom(_harness: object) -> None:
        raise HarnessUnavailableError(unavailable)

    monkeypatch.setattr("band_wezterm.agent.launch.spawn_additional_tab", spawn)
    monkeypatch.setattr("band_wezterm.tui.managed_agent_actions.preflight_managed_agent", boom)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    spawn.assert_not_called()
    assert control_app.agents_store.status == unavailable


async def test_start_agent_aborts_when_profile_removed_mid_preflight(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    control_app.managed_agents.record(
        ManagedAgentProfile(
            agent_id=IDLE_AGENT_ID,
            name="Beta",
            harness=HarnessId.CODEX,
        )
    )
    spawn = MagicMock()

    def remove_during_preflight(_harness: object) -> None:
        control_app.managed_agents.remove(IDLE_AGENT_ID)

    monkeypatch.setattr("band_wezterm.agent.launch.spawn_additional_tab", spawn)
    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.preflight_managed_agent",
        remove_during_preflight,
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    spawn.assert_not_called()
    assert control_app.agents_store.status == NO_MANAGED_PROFILE_MESSAGE


async def test_start_agent_aborts_when_harness_never_settles(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    control_app.managed_agents.record(
        ManagedAgentProfile(
            agent_id=IDLE_AGENT_ID,
            name="Beta",
            harness=HarnessId.CODEX,
        )
    )
    spawn = MagicMock()
    flip = {HarnessId.CODEX: HarnessId.COPILOT, HarnessId.COPILOT: HarnessId.CODEX}

    def never_settle(harness: object) -> None:
        if not isinstance(harness, HarnessId):
            return
        current = control_app.managed_agents.get(IDLE_AGENT_ID)
        assert current is not None
        control_app.managed_agents.record(
            current.model_copy(update={"harness": flip[harness]})
        )

    monkeypatch.setattr("band_wezterm.agent.launch.spawn_additional_tab", spawn)
    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.preflight_managed_agent",
        never_settle,
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    spawn.assert_not_called()
    assert control_app.agents_store.status == PROFILE_HARNESS_UNSTABLE_MESSAGE
    durable = control_app.managed_agents.get(IDLE_AGENT_ID)
    assert durable is not None
    assert control_app.agents_store.find(IDLE_AGENT_ID).harness is durable.harness


async def test_start_agent_aborts_when_harness_changes_after_preflight(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-preflight re-get must abort if harness drifted before spawn."""
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    control_app.managed_agents.record(
        ManagedAgentProfile(
            agent_id=IDLE_AGENT_ID,
            name="Beta",
            harness=HarnessId.CODEX,
        )
    )
    spawn = MagicMock()
    original = AgentsScreen._preflight_launch_profile

    async def drift_after_preflight(self, agent_id, profile):
        result = await original(self, agent_id, profile)
        if result is not None:
            current = self.control.managed_agents.get(agent_id)
            assert current is not None
            self.control.managed_agents.record(
                current.model_copy(update={"harness": HarnessId.COPILOT})
            )
        return result

    monkeypatch.setattr(AgentsScreen, "_preflight_launch_profile", drift_after_preflight)
    monkeypatch.setattr("band_wezterm.agent.launch.spawn_additional_tab", spawn)
    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.preflight_managed_agent",
        lambda _h: None,
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    spawn.assert_not_called()
    assert control_app.agents_store.status == PROFILE_HARNESS_UNSTABLE_MESSAGE
    assert control_app.agents_store.find(IDLE_AGENT_ID).harness is HarnessId.COPILOT


async def test_start_agent_aborts_when_profile_removed_after_preflight(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CLAUDE_SDK)
    band_client.list_my_agents.return_value = [target]
    band_client.managed_agent_api_key.return_value = "band_a_managed"
    control_app.window_id = 42
    control_app.managed_agents.record(
        ManagedAgentProfile(
            agent_id=IDLE_AGENT_ID,
            name="Beta",
            harness=HarnessId.CODEX,
        )
    )
    spawn = MagicMock()
    original = AgentsScreen._preflight_launch_profile

    async def remove_after_preflight(self, agent_id, profile):
        result = await original(self, agent_id, profile)
        if result is not None:
            self.control.managed_agents.remove(agent_id)
        return result

    monkeypatch.setattr(AgentsScreen, "_preflight_launch_profile", remove_after_preflight)
    monkeypatch.setattr("band_wezterm.agent.launch.spawn_additional_tab", spawn)
    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.preflight_managed_agent",
        lambda _h: None,
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    spawn.assert_not_called()
    assert control_app.agents_store.status == NO_MANAGED_PROFILE_MESSAGE
    assert control_app.managed_agents.get(IDLE_AGENT_ID) is None
