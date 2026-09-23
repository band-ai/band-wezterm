"""Opt-in live platform lifecycle for Band rooms and managed agents."""

from __future__ import annotations

from contextlib import suppress
from uuid import uuid4

import pytest

from band_wezterm.client import BandClient
from band_wezterm.config import load_settings
from tests.live_settings import LIVE_SENDER_NAME, user_api_key

pytestmark = pytest.mark.live_platform

RESOURCE_PREFIX = "wezterm-platform-e2e"
AGENT_DESCRIPTION = "Band WezTerm live platform resource lifecycle"
MESSAGE_BODY = "Band WezTerm verifies durable room delivery."


def _resource_name() -> str:
    return f"{RESOURCE_PREFIX}-{uuid4().hex[:8]}"


async def _has_agent(client: BandClient, agent_id: str, name: str) -> bool:
    return any(agent.id == agent_id for agent in await client.list_my_agents(name=name))


async def _has_room(client: BandClient, room_id: str) -> bool:
    return any(room.id == room_id for room in await client.list_my_chats())


@pytest.mark.asyncio
async def test_live_platform_resource_lifecycle() -> None:
    """Create, use, remove, and prove deletion of platform-owned resources."""
    api_key = user_api_key()
    if not api_key:
        pytest.skip("BAND_API_KEY_USER not set (see .env.test)")

    client = BandClient.from_user_api_key(api_key, load_settings())
    name = _resource_name()
    agent_id: str | None = None
    room_id: str | None = None
    participant_added = False

    try:
        assert await client.whoami()

        agent = await client.create_agent(name=name, description=AGENT_DESCRIPTION)
        agent_id = agent.id
        assert await _has_agent(client, agent_id, name)
        assert client.managed_agent_api_key(agent_id)

        room = await client.create_room(title=name)
        room_id = room.id
        assert await _has_room(client, room_id)

        await client.add_participant(room_id, agent_id)
        participant_added = True
        assert any(
            participant.id == agent_id
            for participant in await client.list_participants(room_id)
        )

        delivered = await client.send_message(
            room_id,
            MESSAGE_BODY,
            mentions=[(agent_id, agent.name)],
            sender_name=LIVE_SENDER_NAME,
        )
        assert any(
            message.id == delivered.id and MESSAGE_BODY in (message.content or "")
            for message in await client.list_messages(room_id)
        )

        await client.remove_participant(room_id, agent_id)
        participant_added = False
        assert all(
            participant.id != agent_id
            for participant in await client.list_participants(room_id)
        )

        await client.delete_room(room_id)
        assert not await _has_room(client, room_id)
        room_id = None

        await client.delete_agent(agent_id)
        assert not await _has_agent(client, agent_id, name)
        assert client.managed_agent_api_key(agent_id) is None
        agent_id = None
    finally:
        if participant_added and room_id is not None and agent_id is not None:
            with suppress(Exception):
                await client.remove_participant(room_id, agent_id)
        if room_id is not None:
            with suppress(Exception):
                await client.delete_room(room_id)
        if agent_id is not None:
            with suppress(Exception):
                await client.delete_agent(agent_id)
        await client.aclose()
