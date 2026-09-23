"""Opt-in live Control flow: register, persist, join a room, start, and stop."""

from __future__ import annotations

from contextlib import suppress
from pathlib import Path
from uuid import uuid4

import pytest

from band_wezterm.agent_draft import apply_draft_patch
from band_wezterm.client import BandClient
from band_wezterm.config import load_settings
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.tui.control_app import AppScreen, ControlApp
from band_wezterm.tui.screens.agents import AgentsScreen
from band_wezterm.tui.screens.register_agent import RegisterAgentScreen
from tests.live_harness import pick_harness
from tests.live_settings import user_api_key
from tests.tui import settle

pytestmark = pytest.mark.live_platform

LIVE_AGENT_DESCRIPTION = "Band WezTerm live Control registration flow"
LIVE_NAME_PREFIX = "wezterm-control-e2e"


class ApiKeySession:
    """Satisfy the Control gate while BandClient authenticates with a test API key."""

    token_generation = 0

    def has_stored_tokens(self) -> bool:
        return True


@pytest.mark.asyncio
async def test_live_control_registers_persists_joins_and_stops_an_agent() -> None:
    api_key = user_api_key()
    if not api_key:
        pytest.skip("BAND_API_KEY_USER not set (see .env.test)")
    harness = pick_harness()
    if harness is None:
        pytest.skip("No harness adapter extra installed (uv sync --extra agents)")

    settings = load_settings()
    client = BandClient.from_user_api_key(api_key, settings)
    profiles = ManagedAgentStore(settings=settings)
    name = f"{LIVE_NAME_PREFIX}-{uuid4().hex[:8]}"
    app = ControlApp(
        settings=settings,
        host_auth=ApiKeySession(),
        client=client,
        managed_agents=profiles,
        initial_screen=AppScreen.AGENTS,
    )
    agent_id: str | None = None
    room_id: str | None = None
    joined = False
    started = False

    try:
        async with app.run_test() as pilot:
            await settle(pilot)
            assert isinstance(app.screen, AgentsScreen)

            await pilot.press("n")
            await settle(pilot)
            registration = app.screen
            assert isinstance(registration, RegisterAgentScreen)
            registration.draft = apply_draft_patch(
                registration.draft,
                harness=harness,
                name=name,
                description=LIVE_AGENT_DESCRIPTION,
            )
            registration.step = registration._steps_for_draft()[-1]
            registration._advance()
            await settle(pilot)

            registered = next(
                agent
                for agent in await client.list_my_agents(name=name)
                if agent.name == name
            )
            agent_id = registered.id
            profile = profiles.get(agent_id)
            assert profile is not None
            assert profile.harness is harness
            assert client.managed_agent_api_key(agent_id)

            room = await app.room_operations.create(f"{name}-room")
            room_id = room.id
            await client.add_participant(room_id, agent_id)
            joined = True
            assert agent_id in {
                participant.id for participant in await client.list_participants(room_id)
            }

            worker = await app.agent_operations.start(agent_id, cwd=Path.cwd())
            started = True
            assert worker.agent_id == agent_id
            assert agent_id in {
                record.agent_id for record in await app.agent_lifecycle.workers()
            }
    finally:
        if started and agent_id is not None:
            with suppress(Exception):
                await app.agent_operations.stop(agent_id)
        if joined and room_id is not None and agent_id is not None:
            with suppress(Exception):
                await client.remove_participant(room_id, agent_id)
        if room_id is not None:
            with suppress(Exception):
                await client.delete_room(room_id)
        if agent_id is not None:
            with suppress(Exception):
                await client.delete_agent(agent_id)
            with suppress(Exception):
                profiles.remove(agent_id)
