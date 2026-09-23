"""Opt-in live: one detached harness agent serves two rooms in sequence."""

from __future__ import annotations

import time
from contextlib import suppress

import pytest

from band_wezterm.client import BandClient
from band_wezterm.config import load_settings
from tests.live_harness import (
    message_has_token,
    pick_harness,
    start_agent_runtime,
    stop_agent_runtime,
    wait_for_reply_token,
)
from tests.live_settings import LIVE_SENDER_NAME, user_api_key

pytestmark = pytest.mark.live_platform

FIRST_TOKEN = "band-wezterm-multi-room-first"
SECOND_TOKEN = "band-wezterm-multi-room-second"


@pytest.mark.asyncio
async def test_live_agent_serves_each_room_it_joins_before_start() -> None:
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
    agent_id: str | None = None
    room_ids: list[str] = []
    stamp = int(time.time())
    try:
        agent = await client.create_agent(
            name=f"wezterm-multi-room-{stamp}",
            description="band-wezterm live detached multi-room flow",
        )
        agent_id = agent.id
        managed_key = client.managed_agent_api_key(agent_id)
        assert managed_key, "create_agent must persist the managed API key"

        first_room = await client.create_room(title=f"band-wezterm-first-{stamp}")
        room_ids.append(first_room.id)
        await client.add_participant(first_room.id, agent_id)
        second_room = await client.create_room(title=f"band-wezterm-second-{stamp}")
        room_ids.append(second_room.id)
        await client.add_participant(second_room.id, agent_id)

        runtime, task = await start_agent_runtime(
            harness=harness,
            agent_id=agent_id,
            api_key=managed_key,
            rest_url=settings.band_base_url,
            ws_url=settings.band_ws_url,
        )

        first_prompt = f"Reply with exactly: {FIRST_TOKEN}"
        await client.send_message(
            first_room.id,
            first_prompt,
            mentions=[(agent_id, agent.name)],
            sender_name=LIVE_SENDER_NAME,
        )
        first_messages = await wait_for_reply_token(
            client,
            first_room.id,
            token=FIRST_TOKEN,
            excluding=first_prompt,
        )
        assert message_has_token(first_messages, FIRST_TOKEN, excluding=first_prompt)

        second_prompt = f"Reply with exactly: {SECOND_TOKEN}"
        await client.send_message(
            second_room.id,
            second_prompt,
            mentions=[(agent_id, agent.name)],
            sender_name=LIVE_SENDER_NAME,
        )
        second_messages = await wait_for_reply_token(
            client,
            second_room.id,
            token=SECOND_TOKEN,
            excluding=second_prompt,
        )
        assert message_has_token(second_messages, SECOND_TOKEN, excluding=second_prompt)
        assert any(
            agent.name.casefold() in message.author_name.casefold()
            for message in second_messages
        )
    finally:
        await stop_agent_runtime(runtime, task)
        for room_id in room_ids:
            if agent_id is not None:
                with suppress(Exception):
                    await client.remove_participant(room_id, agent_id)
        if agent_id is not None:
            with suppress(Exception):
                await client.delete_agent(agent_id)
        await client.aclose()
