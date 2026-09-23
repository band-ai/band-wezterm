"""Shared Band-screen test tooling: autospec'd platform seams and a Pilot helper.

Every fixture here mocks exactly one seam — the platform client and the token
store — so the tests exercise the real screens, stores and widgets.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, create_autospec

import pytest

from band_wezterm.agent.opencode_server import OpenCodeServerManager
from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.backends import TuningOption
from band_wezterm.catalogs import HarnessCatalog, ModelCatalogEntry, ModelCatalogService
from band_wezterm.client import (
    AgentRecord,
    BandClient,
    ParticipantRecord,
    RoomPage,
    RoomRecord,
)
from band_wezterm.config import Settings
from band_wezterm.identity import AvatarKind, HarnessId, agent_accent, parse_harness
from band_wezterm.local_state import StarredRooms
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.preferences import PreferencesStore
from band_wezterm.room_color import room_accent
from band_wezterm.supervisor import SupervisorClient
from band_wezterm.tui.control_app import AppScreen, ControlApp

HOST_USER_ID = "b1c0f6f4-0f6e-4a2f-9a5e-2f9f0d2b7c11"
ACCESS_TOKEN = "access-token"


def agent(
    agent_id: str,
    name: str,
    harness: HarnessId | str | None = None,
) -> AgentRecord:
    resolved = harness if isinstance(harness, HarnessId) else parse_harness(harness)
    return AgentRecord(
        id=agent_id,
        name=name,
        kind=AvatarKind.AGENT,
        color=agent_accent(agent_id),
        harness=resolved,
    )


def participant(record: AgentRecord) -> ParticipantRecord:
    return ParticipantRecord(
        id=record.id, name=record.name, kind=record.kind, color=record.color
    )


def room(room_id: str, title: str) -> RoomRecord:
    return RoomRecord(id=room_id, title=title, color=room_accent(room_id))


@pytest.fixture
def band_client() -> MagicMock:
    """Platform facade with empty catalogs — tests fill in what they need."""
    client = create_autospec(BandClient, spec_set=True, instance=True)
    client.whoami.return_value = HOST_USER_ID
    client.list_my_agents.return_value = []
    client.list_my_chats.return_value = []
    client.list_room_page.return_value = RoomPage(
        rooms=(), next_cursor=None, has_more=False
    )
    client.list_participants.return_value = []
    client.list_directory.return_value = []
    client.list_messages.return_value = []
    client.subscribe_realtime.return_value = lambda: None
    return client


@pytest.fixture
def host_auth() -> MagicMock:
    auth = create_autospec(HostAuth, spec_set=True, instance=True)
    auth.has_stored_tokens.return_value = True
    auth.get_access_token.return_value = ACCESS_TOKEN
    return auth


@pytest.fixture
def control_app(
    host_auth: MagicMock, band_client: MagicMock, tmp_path: Path
) -> ControlApp:
    opencode_server = OpenCodeServerManager()
    supervisor = create_autospec(SupervisorClient, spec_set=True, instance=True)
    supervisor.list_workers.return_value = ()

    async def codex_catalog() -> HarnessCatalog:
        efforts = (
            TuningOption(id="low", label="Low"),
            TuningOption(id="medium", label="Medium"),
            TuningOption(id="high", label="High"),
        )
        return HarnessCatalog(
            models=(
                ModelCatalogEntry(
                    id="gpt-5.6-sol",
                    label="GPT-5.6 Sol",
                    efforts=efforts,
                ),
            ),
            default_model_id="gpt-5.6-sol",
        )

    async def empty_catalog() -> HarnessCatalog:
        return HarnessCatalog(models=())

    catalogs = ModelCatalogService(
        opencode_server,
        loaders={
            HarnessId.CLAUDE_SDK: empty_catalog,
            HarnessId.CODEX: codex_catalog,
            HarnessId.COPILOT_SDK: empty_catalog,
            HarnessId.OPENCODE: empty_catalog,
        },
    )
    return ControlApp(
        settings=Settings(),
        host_auth=host_auth,
        client=band_client,
        starred=StarredRooms(tmp_path / "local_state.json"),
        managed_agents=ManagedAgentStore(tmp_path / "managed_agents.json"),
        preferences=PreferencesStore(tmp_path / "preferences.json"),
        opencode_server=opencode_server,
        model_catalogs=catalogs,
        supervisor=supervisor,
        initial_screen=AppScreen.AGENTS,
    )
