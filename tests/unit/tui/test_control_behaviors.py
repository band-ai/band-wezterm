"""Pilot tests for the Control tab behaviors that are easy to regress."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from textual.widgets import ListView, Static

from band_wezterm.agent.adapters import HarnessUnavailableError
from band_wezterm.agent_draft import AgentDraft, apply_draft_patch
from band_wezterm.backends import AgentTuning
from band_wezterm.client import MessageRecord
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import ManagedAgentProfile
from band_wezterm.tui.control_app import ControlApp
from band_wezterm.tui.screens.agents import (
    NO_MANAGED_KEY_MESSAGE,
    NO_MANAGED_PROFILE_MESSAGE,
    PROFILE_HARNESS_UNSTABLE_MESSAGE,
    AgentRow,
    AgentsScreen,
)
from band_wezterm.tui.screens.agents import Id as AgentId
from band_wezterm.tui.screens.agents import selector as agent_selector
from band_wezterm.tui.screens.register_agent import Id as RegisterId
from band_wezterm.tui.screens.register_agent import RegisterAgentScreen
from band_wezterm.tui.screens.register_agent import selector as register_selector
from band_wezterm.tui.screens.rooms import Id as RoomId
from band_wezterm.tui.screens.rooms import (
    IdentityRow,
    RoomDetailScreen,
    RoomsScreen,
)
from band_wezterm.tui.screens.rooms import selector as room_selector
from band_wezterm.tui.screens.sign_in import SignInScreen
from band_wezterm.wezterm_cli import PaneId

from .conftest import agent, participant, room, settle

RUNNING_AGENT_ID = "0f5d0b7c-1a3e-4c5b-9d2f-6a7b8c9d0e1f"
IDLE_AGENT_ID = "3c2b1a09-8f7e-4d6c-5b4a-3928176054f3"
ROOM_ID = "9a8b7c6d-5e4f-4a3b-2c1d-0e9f8a7b6c5d"
AGENT_PANE = PaneId(11)
KEYRING_FAILURE_MESSAGE = "keyring write failed"
PROFILE_RECORD_FAILURE_MESSAGE = "disk full"


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

    band_client.list_messages.assert_awaited_once_with(
        ROOM_ID, limit=control_app.preferences.current.chat_messages_limit
    )


async def test_start_agent_spawns_agent_module_pane(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Start must spawn ``python -m band_wezterm.agent``, not a PoC cat tab."""
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
    preflighted: list[object] = []

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
        "band_wezterm.tui.screens.agents.preflight_harness",
        preflighted.append,
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
        # Load-path projection — before Start's own sync can mask a miss.
        assert control_app.agents_store.find(IDLE_AGENT_ID).harness is HarnessId.CODEX
        await pilot.press("s")
        await settle(pilot)
        assert control_app.agents_store.is_running(IDLE_AGENT_ID)
        assert HarnessId.CODEX.value in (control_app.agents_store.status or "")

    assert len(spawned) == 1
    window_id, _cwd, command = spawned[0]
    assert window_id == 42
    assert "-m" in command
    assert "band_wezterm.agent" in command
    assert "band_a_managed" not in " ".join(command)
    assert "--model" in command
    assert "o3" in command
    assert "--reasoning" in command
    assert "high" in command
    assert command[command.index("--harness") + 1] == HarnessId.CODEX.value
    assert preflighted == [HarnessId.CODEX]
    assert control_app.agents_store.find(IDLE_AGENT_ID).harness is HarnessId.CODEX


async def test_start_agent_repreflights_through_chained_midflight_reconfigure(
    control_app: ControlApp,
    band_client: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
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
        "band_wezterm.tui.screens.agents.spawn_additional_tab", fake_spawn
    )
    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.set_tab_title", lambda *_a, **_k: None
    )
    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.preflight_harness",
        fake_preflight,
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
    monkeypatch.setattr("band_wezterm.tui.screens.agents.spawn_additional_tab", spawn)

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
    monkeypatch.setattr("band_wezterm.tui.screens.agents.spawn_additional_tab", spawn)

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


async def test_reconfigure_records_profile_then_updates_keyring(
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

    band_client.update_managed_harness.assert_called_once_with(
        IDLE_AGENT_ID, HarnessId.COPILOT_SDK
    )
    stored = control_app.managed_agents.get(IDLE_AGENT_ID)
    assert stored is not None
    assert stored.harness is HarnessId.COPILOT_SDK
    assert control_app.agents_store.find(IDLE_AGENT_ID).harness is HarnessId.COPILOT_SDK
    assert "Reconfigured Beta" in (control_app.agents_store.status or "")


async def test_reconfigure_restores_previous_profile_when_keyring_fails(
    control_app: ControlApp, band_client: MagicMock
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
    band_client.update_managed_harness.side_effect = RuntimeError(KEYRING_FAILURE_MESSAGE)

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
        assert KEYRING_FAILURE_MESSAGE in str(
            screen.query_one(register_selector(RegisterId.STATUS), Static).render()
        )

    assert control_app.managed_agents.get(IDLE_AGENT_ID) == previous
    assert control_app.agents_store.find(IDLE_AGENT_ID).harness is HarnessId.CODEX


async def test_reconfigure_removes_provisional_profile_when_keyring_fails(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    target = agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX)
    band_client.list_my_agents.return_value = [target]
    band_client.update_managed_harness.side_effect = RuntimeError(KEYRING_FAILURE_MESSAGE)

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
        assert KEYRING_FAILURE_MESSAGE in str(
            screen.query_one(register_selector(RegisterId.STATUS), Static).render()
        )

    assert control_app.managed_agents.get(IDLE_AGENT_ID) is None
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


async def test_delete_requires_confirmation(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    band_client.list_my_agents.return_value = [
        agent(IDLE_AGENT_ID, "Beta", harness=HarnessId.CODEX),
    ]
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



async def test_delete_room_requires_confirmation(
    control_app: ControlApp, band_client: MagicMock
) -> None:
    """Delete on the rooms list is two-press, matching agents."""
    target = room(ROOM_ID, "Core")
    band_client.list_my_chats.return_value = [target]

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
    band_client.list_my_chats.return_value = [target]
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


async def test_reconfigure_surfaces_rollback_failure_when_restore_save_fails(
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
    band_client.update_managed_harness.side_effect = RuntimeError(KEYRING_FAILURE_MESSAGE)
    rollback_message = "rollback disk full"
    saves = {"count": 0}
    real_save = control_app.managed_agents._save

    def flaky_save() -> None:
        saves["count"] += 1
        # First save: provisional next_profile succeeds.
        # Second save: restore of previous fails.
        if saves["count"] >= 2:
            raise OSError(rollback_message)
        real_save()

    monkeypatch.setattr(control_app.managed_agents, "_save", flaky_save)

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("c")
        await settle(pilot)
        screen = control_app.screen
        assert isinstance(screen, RegisterAgentScreen)
        screen.draft = apply_draft_patch(screen.draft, harness=HarnessId.COPILOT_SDK)
        screen._submit_reconfigure()
        await settle(pilot)
        status = str(
            screen.query_one(register_selector(RegisterId.STATUS), Static).render()
        )
        assert KEYRING_FAILURE_MESSAGE in status
        assert rollback_message in status
        assert "profile rollback failed" in status

    # Best-effort: provisional next_profile remains after failed restore.
    stored = control_app.managed_agents.get(IDLE_AGENT_ID)
    assert stored is not None
    assert stored.harness is HarnessId.COPILOT_SDK


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

    monkeypatch.setattr("band_wezterm.tui.screens.agents.spawn_additional_tab", spawn)
    monkeypatch.setattr("band_wezterm.tui.screens.agents.preflight_harness", boom)

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

    monkeypatch.setattr("band_wezterm.tui.screens.agents.spawn_additional_tab", spawn)
    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.preflight_harness",
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

    monkeypatch.setattr("band_wezterm.tui.screens.agents.spawn_additional_tab", spawn)
    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.preflight_harness",
        never_settle,
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    spawn.assert_not_called()
    assert control_app.agents_store.status == PROFILE_HARNESS_UNSTABLE_MESSAGE


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
    monkeypatch.setattr("band_wezterm.tui.screens.agents.spawn_additional_tab", spawn)
    monkeypatch.setattr(
        "band_wezterm.tui.screens.agents.preflight_harness",
        lambda _h: None,
    )

    async with control_app.run_test() as pilot:
        await settle(pilot)
        await pilot.press("s")
        await settle(pilot)

    spawn.assert_not_called()
    assert control_app.agents_store.status == PROFILE_HARNESS_UNSTABLE_MESSAGE

