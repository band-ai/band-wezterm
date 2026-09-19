"""Opt-in live: full agent + room + multi-turn human/agent chat."""

from __future__ import annotations

import time
from contextlib import suppress

import pytest

from tests.live_harness import (
    message_has_token,
    pick_harness,
    start_agent_runtime,
    stop_agent_runtime,
    wait_for_reply_token,
)
from tests.live_settings import user_api_key

pytestmark = pytest.mark.live_platform

TURN_ONE_PROMPT = "Reply with exactly: band-wezterm-turn-one"
TURN_ONE_TOKEN = "band-wezterm-turn-one"
TURN_TWO_PROMPT = "Reply with exactly: band-wezterm-turn-two"
TURN_TWO_TOKEN = "band-wezterm-turn-two"


@pytest.mark.asyncio
async def test_live_full_chat_agent_and_human_round_trips() -> None:
    from band_wezterm.client import BandClient
    from band_wezterm.config import load_settings

    api_key = user_api_key()
    if not api_key:
        pytest.skip("BAND_API_KEY_USER not set (see .env.test)")

    harness = pick_harness()
    if harness is None:
        pytest.skip("No harness adapter extra installed (uv sync --extra agents)")

    settings = load_settings()
    client = BandClient.from_user_api_key(api_key, settings)
    runtime = None
    task = None
    room_id = None
    agent_id = None
    stamp = int(time.time())
    agent_name = f"wezterm-chat-{stamp}"

    try:
        assert await client.whoami()

        record = await client.create_agent(
            name=agent_name,
            description="band-wezterm full chat live flow",
            harness=harness,
        )
        agent_id = record.id
        managed = client.managed_agent_api_key(agent_id)
        assert managed, "create_agent must persist the one-time managed API key"
        assert any(
            agent.id == agent_id
            for agent in await client.list_my_agents(name=agent_name)
        )

        room = await client.create_room(title=f"band-wezterm-full-chat-{stamp}")
        room_id = room.id
        assert any(item.id == room_id for item in await client.list_my_chats())

        await client.add_participant(room_id, agent_id)
        assert any(
            participant.id == agent_id
            for participant in await client.list_participants(room_id)
        )

        runtime, task = await start_agent_runtime(
            harness=harness,
            agent_id=agent_id,
            api_key=managed,
            rest_url=settings.band_base_url,
            ws_url=settings.band_ws_url,
        )

        assert (
            await client.send_message(
                room_id,
                TURN_ONE_PROMPT,
                mention_id=agent_id,
                mention_name=record.name,
            )
        ).id
        after_one = await wait_for_reply_token(
            client, room_id, token=TURN_ONE_TOKEN, excluding=TURN_ONE_PROMPT
        )
        assert message_has_token(
            after_one, TURN_ONE_TOKEN, excluding=TURN_ONE_PROMPT
        ), f"Agent never replied to turn one: {[m.content for m in after_one]}"
        assert any(TURN_ONE_PROMPT in (m.content or "") for m in after_one)

        assert (
            await client.send_message(
                room_id,
                TURN_TWO_PROMPT,
                mention_id=agent_id,
                mention_name=record.name,
            )
        ).id
        after_two = await wait_for_reply_token(
            client, room_id, token=TURN_TWO_TOKEN, excluding=TURN_TWO_PROMPT
        )
        assert message_has_token(
            after_two, TURN_TWO_TOKEN, excluding=TURN_TWO_PROMPT
        ), f"Agent never replied to turn two: {[m.content for m in after_two]}"

        history = await client.list_messages(room_id)
        contents = [m.content or "" for m in history]
        assert any(TURN_ONE_PROMPT in body for body in contents), contents
        assert any(TURN_TWO_PROMPT in body for body in contents), contents
        assert message_has_token(history, TURN_ONE_TOKEN, excluding=TURN_ONE_PROMPT)
        assert message_has_token(history, TURN_TWO_TOKEN, excluding=TURN_TWO_PROMPT)
        assert any(
            m.author_name and record.name.lower() in m.author_name.lower()
            for m in history
        ), contents

        await client.remove_participant(room_id, agent_id)
        assert all(
            participant.id != agent_id
            for participant in await client.list_participants(room_id)
        )
    finally:
        await stop_agent_runtime(runtime, task)
        if room_id is not None and agent_id is not None:
            with suppress(Exception):
                await client.remove_participant(room_id, agent_id)
        if agent_id is not None:
            with suppress(Exception):
                await client.delete_agent(agent_id)
        await client.aclose()
