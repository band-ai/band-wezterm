"""High-value end-to-end behaviors for the disposable Band surfaces."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from band_rest.core.api_error import ApiError
from textual import events
from textual.widgets import Input, Static

from band_wezterm.agent_draft import apply_draft_patch
from band_wezterm.backends import AgentTuning
from band_wezterm.client import (
    MessagePage,
    MessageRecord,
    RealtimeEvent,
    RealtimeEventKind,
)
from band_wezterm.diagnostics import diagnostics_log_path
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import ManagedAgentProfile
from band_wezterm.supervisor import WorkerRecord, WorkerState
from band_wezterm.supervisor.client import SupervisorError
from band_wezterm.tui.control_app import AppScreen, ControlApp, InitialAgentAction
from band_wezterm.tui.screens.agents import AgentsScreen
from band_wezterm.tui.screens.event_type_filter import EventTypeFilterScreen
from band_wezterm.tui.screens.register_agent import (
    Id as RegisterId,
)
from band_wezterm.tui.screens.register_agent import (
    RegisterAgentScreen,
    WizardStep,
)
from band_wezterm.tui.screens.rooms import (
    ChatEventRow,
    ChatTimeline,
    RoomDetailScreen,
    participant_mention_text,
)
from band_wezterm.tui.screens.rooms import Id as RoomId
from band_wezterm.tui.screens.rooms import selector as room_selector
from band_wezterm.tui.screens.settings import Id as SettingsId
from band_wezterm.tui.screens.settings import selector as settings_selector
from band_wezterm.tui.screens.sign_in import SignInScreen
from band_wezterm.tui.screens.warmup import WarmupScreen
from band_wezterm.tui.widgets import MarkdownComposer
from tests.tui import settle

from .conftest import agent, participant, room

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


async def test_worker_poll_waits_for_the_readiness_gate(
    control_app: ControlApp,
) -> None:
    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.supervisor.list_workers.reset_mock()
        control_app._surface_ready = False
        await control_app._reconcile_workers()
        control_app.supervisor.list_workers.assert_not_awaited()

        control_app._surface_ready = True
        await control_app._reconcile_workers()

    control_app.supervisor.list_workers.assert_awaited_once()


async def test_warmup_retries_a_cold_supervisor_before_exposing_the_workspace(
    control_app: ControlApp,
) -> None:
    control_app.supervisor.connect.side_effect = [
        SupervisorError("runtime is still starting"),
        None,
    ]
    control_app.initial_screen = AppScreen.ROOMS

    async with control_app.run_test() as pilot:
        await settle(pilot)
        assert isinstance(control_app.screen, WarmupScreen)
        assert not control_app.surface_ready

        await pilot.press("enter")
        await settle(pilot)

        assert control_app.surface_ready
        assert control_app.screen.__class__.__name__ == "RoomsScreen"

    assert control_app.supervisor.connect.await_count == 2


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


async def test_room_picker_adds_a_candidate_after_the_selection_event(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    selected = agent(AGENT_ID, "Architect", harness=HarnessId.CODEX)
    target_room = room(ROOM_ID, "Planning")
    band_client.list_my_agents.return_value = [selected]

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target_room)
        await settle(pilot)
        await pilot.press("a")
        await settle(pilot)
        await pilot.press("enter")
        await settle(pilot)
        assert not control_app.rooms_store.picker_open

    band_client.add_participant.assert_awaited_once_with(ROOM_ID, AGENT_ID)


async def test_room_flow_creates_adds_removes_and_deletes_without_stale_ui_state(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    selected = agent(AGENT_ID, "Architect", harness=HarnessId.CODEX)
    created = room(ROOM_ID, "Planning")
    participants = []
    band_client.create_room.return_value = created
    band_client.list_my_agents.return_value = [selected]
    band_client.list_participants.side_effect = lambda _room_id: list(participants)
    band_client.add_participant.side_effect = lambda _room_id, _agent_id: (
        participants.append(participant(selected))
    )
    band_client.remove_participant.side_effect = lambda _room_id, agent_id: (
        participants.remove(
            next(entry for entry in participants if entry.id == agent_id)
        )
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.action_show_rooms()
        await settle(pilot)
        await pilot.press("n")
        draft = control_app.screen.query_one(room_selector(RoomId.DRAFT_TITLE), Input)
        draft.value = created.title
        await pilot.press("enter")
        await settle(pilot)

        screen = control_app.screen
        assert isinstance(screen, RoomDetailScreen)
        await pilot.press("a", "enter")
        await settle(pilot)
        assert [entry.id for entry in screen.store.participants] == [AGENT_ID]

        await pilot.press("x")
        await settle(pilot)
        assert not screen.store.participants

        await pilot.press("delete", "delete")
        await settle(pilot)
        assert not isinstance(control_app.screen, RoomDetailScreen)

    band_client.add_participant.assert_awaited_once_with(ROOM_ID, AGENT_ID)
    band_client.remove_participant.assert_awaited_once_with(ROOM_ID, AGENT_ID)
    band_client.delete_room.assert_awaited_once_with(ROOM_ID)


async def test_registration_submits_once_when_the_final_step_is_repeated(
    control_app: ControlApp, band_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = agent(AGENT_ID, "Architect", harness=HarnessId.CLAUDE_SDK)
    band_client.create_agent.return_value = registered
    monkeypatch.setattr(
        "band_wezterm.tui.screens.register_agent.preflight_managed_agent",
        lambda *_args, **_kwargs: None,
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.action_show_agents()
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)
        screen.draft = apply_draft_patch(
            screen.draft,
            name=registered.name,
            description="Designs durable systems.",
        )
        screen.step = screen._steps_for_draft()[-1]
        screen._advance()
        screen._advance()
        await settle(pilot)

    band_client.create_agent.assert_awaited_once_with(
        name=registered.name,
        description="Designs durable systems.",
    )


async def test_registered_agent_can_start_and_stop_in_the_same_control_session(
    control_app: ControlApp, band_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    registered = agent(AGENT_ID, "Architect", harness=HarnessId.CLAUDE_SDK)
    running = _worker(registered.id, registered.name)
    stopping = running.model_copy(update={"state": WorkerState.STOPPING})
    band_client.create_agent.return_value = registered
    band_client.list_my_agents.return_value = [registered]
    control_app.supervisor.start.return_value = running
    control_app.supervisor.stop.return_value = stopping
    monkeypatch.setattr(
        "band_wezterm.tui.screens.register_agent.preflight_managed_agent",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "band_wezterm.tui.managed_agent_actions.preflight_managed_agent",
        lambda *_args, **_kwargs: None,
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        registration = control_app.screen
        assert isinstance(registration, RegisterAgentScreen)
        registration.draft = apply_draft_patch(
            registration.draft,
            name=registered.name,
            description="Designs durable systems.",
        )
        registration.step = registration._steps_for_draft()[-1]
        registration._advance()
        await settle(pilot)

        assert isinstance(control_app.screen, AgentsScreen)
        await pilot.press("s", "x")
        await settle(pilot)

    control_app.supervisor.start.assert_awaited_once_with(AGENT_ID, cwd=Path.cwd())
    control_app.supervisor.stop.assert_awaited_once_with(AGENT_ID)


async def test_registration_name_conflict_returns_to_a_clear_name_step(
    control_app: ControlApp, band_client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    duplicate_name = "Architect"
    band_client.create_agent.side_effect = ApiError(
        status_code=422,
        body={
            "error": {
                "code": "validation_error",
                "details": {"name": ["has already been taken"]},
            }
        },
    )
    monkeypatch.setattr(
        "band_wezterm.tui.screens.register_agent.preflight_managed_agent",
        lambda *_args, **_kwargs: None,
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("n")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)
        screen.draft = apply_draft_patch(
            screen.draft,
            name=duplicate_name,
            description="Designs durable systems.",
        )
        screen.step = screen._steps_for_draft()[-1]
        screen._advance()
        await settle(pilot)

        assert screen.step is WizardStep.NAME
        status = screen.query_one(f"#{RegisterId.STATUS.value}", Static)
        assert duplicate_name in str(status.render())


async def test_room_loads_message_history(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    target_room = room(ROOM_ID, "Planning")
    message = MessageRecord(
        id="message-1",
        content="Decide the lifecycle.",
        author_name="Architect",
    )
    band_client.list_message_page.return_value = MessagePage(
        messages=(message,), next_cursor=None, has_more=False
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target_room)
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RoomDetailScreen)
        assert screen.store.messages == [message]


async def test_room_appends_realtime_messages_without_rebuilding_history(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    target_room = room(ROOM_ID, "Planning")
    history = MessageRecord(
        id="history",
        content="Earlier message.",
        author_name="Architect",
        inserted_at=datetime(2026, 9, 23, 7, 0, tzinfo=UTC),
    )
    band_client.list_message_page.return_value = MessagePage(
        messages=(history,), next_cursor=None, has_more=False
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target_room)
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RoomDetailScreen)

        event = RealtimeEvent(
            kind=RealtimeEventKind.MESSAGE_CREATED,
            room_id=ROOM_ID,
            payload={
                "id": "latest",
                "content": "Latest message.",
                "sender_name": "Architect",
                "inserted_at": "2026-09-23T07:01:00Z",
            },
        )
        with patch(
            "band_wezterm.tui.screens.rooms.refill", new_callable=AsyncMock
        ) as refill:
            screen.on_room_detail_screen_incoming(RoomDetailScreen.Incoming(event))
            await settle(pilot)

        assert refill.await_args_list == []
        assert [row.message.id for row in screen.query(ChatEventRow)] == [
            "history",
            "latest",
        ]


async def test_room_prepends_an_older_cursor_page(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    target_room = room(ROOM_ID, "Planning")
    newest = MessageRecord(id="newest", content="Newest", author_name="Architect")
    older = MessageRecord(id="older", content="Older", author_name="Architect")
    band_client.list_message_page.side_effect = [
        MessagePage(messages=(newest,), next_cursor="older-page", has_more=True),
        MessagePage(messages=(older,), next_cursor=None, has_more=False),
    ]

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target_room)
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RoomDetailScreen)

        with patch(
            "band_wezterm.tui.screens.rooms.refill", new_callable=AsyncMock
        ) as refill:
            screen._load_older_messages()
            await settle(pilot)

        assert [message.id for message in screen.store.messages] == ["older", "newest"]
        assert refill.await_args_list == []

    assert (
        band_client.list_message_page.await_args_list[1].kwargs["cursor"]
        == "older-page"
    )


async def test_room_loads_history_when_the_chat_reaches_its_top(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    target_room = room(ROOM_ID, "Planning")
    newest = MessageRecord(id="newest", content="Newest", author_name="Architect")
    older = MessageRecord(id="older", content="Older", author_name="Architect")
    band_client.list_message_page.side_effect = [
        MessagePage(messages=(newest,), next_cursor="older-page", has_more=True),
        MessagePage(messages=(older,), next_cursor=None, has_more=False),
    ]

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target_room)
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RoomDetailScreen)

        chat = screen.query_one(room_selector(RoomId.CHAT), ChatTimeline)
        chat._on_mouse_scroll_up(
            events.MouseScrollUp(
                chat,
                x=0,
                y=0,
                delta_x=0,
                delta_y=-1,
                button=0,
                shift=False,
                meta=False,
                ctrl=False,
            )
        )
        await settle(pilot)

        assert [message.id for message in screen.store.messages] == ["older", "newest"]
        assert screen._has_older_messages is False


def test_room_colors_mentions_using_the_roster_identity() -> None:
    mentioned = participant(agent(AGENT_ID, "Architect", harness=HarnessId.CODEX))

    rendered = participant_mention_text("Ask @Architect to review.", [mentioned])

    assert rendered is not None
    assert rendered.plain == "Ask @Architect to review."
    assert rendered.spans[0].style.color is not None
    assert rendered.spans[0].style.color.name == mentioned.color


async def test_room_message_and_event_filter_flow(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    selected = agent(AGENT_ID, "Architect", harness=HarnessId.CODEX)
    target_room = room(ROOM_ID, "Planning")
    delivered = MessageRecord(
        id="message-1",
        content="@Architect decide the lifecycle.",
        author_name="You",
    )
    band_client.list_participants.return_value = [participant(selected)]
    band_client.send_message.return_value = delivered

    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.open_room(target_room)
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RoomDetailScreen)

        composer = screen.query_one(room_selector(RoomId.COMPOSER), MarkdownComposer)
        composer.value = "@Architect decide the lifecycle."
        composer.focus()
        await pilot.press("enter")
        await settle(pilot)
        assert screen.store.messages == [delivered]

        before_filter = control_app.preferences.current.chat_event_types
        await pilot.press("escape", "e")
        await settle(pilot)
        assert isinstance(control_app.screen, EventTypeFilterScreen)
        await pilot.press("enter")
        await settle(pilot)
        assert control_app.preferences.current.chat_event_types != before_filter
        await pilot.press("escape")
        await settle(pilot)
        assert control_app.screen is screen

    band_client.send_message.assert_awaited_once_with(
        ROOM_ID,
        "decide the lifecycle.",
        mentions=[(AGENT_ID, selected.name)],
        sender_name="You",
    )


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


async def test_settings_shows_the_active_diagnostics_file(
    control_app: ControlApp,
) -> None:
    async with control_app.run_test() as pilot:
        await settle(pilot)
        control_app.action_show_settings()
        await settle(pilot)
        log_file = control_app.screen.query_one(
            settings_selector(SettingsId.LOG_FILE), Static
        )

    assert str(diagnostics_log_path(settings=control_app.settings)) == str(
        log_file.render()
    )
