"""Opt-in live: start one harness runtime, @mention, assert a reply."""

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
from tests.live_settings import user_api_key

pytestmark = pytest.mark.live_platform

MENTION_PROMPT = "Reply with exactly: band-wezterm-harness-ok"
REPLY_TOKEN = "band-wezterm-harness-ok"


@pytest.mark.asyncio
async def test_live_harness_mention_gets_reply() -> None:
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
    try:
        record = await client.create_agent(
            name=f"wezterm-live-{int(time.time())}",
            description="band-wezterm live harness smoke",
            harness=harness,
        )
        agent_id = record.id
        managed = client.managed_agent_api_key(agent_id)
        if not managed:
            pytest.fail("create_agent did not persist managed API key")

        room = await client.create_room(title="band-wezterm-harness-live")
        room_id = room.id
        await client.add_participant(room_id, agent_id)

        runtime, task = await start_agent_runtime(
            harness=harness,
            agent_id=agent_id,
            api_key=managed,
            rest_url=settings.band_base_url,
            ws_url=settings.band_ws_url,
        )

        await client.send_message(
            room_id,
            MENTION_PROMPT,
            mention_id=agent_id,
            mention_name=record.name,
        )
        messages = await wait_for_reply_token(
            client, room_id, token=REPLY_TOKEN, excluding=MENTION_PROMPT
        )
        assert message_has_token(
            messages, REPLY_TOKEN, excluding=MENTION_PROMPT
        ), "Timed out waiting for harness agent reply to @mention"
    finally:
        await stop_agent_runtime(runtime, task)
        if room_id is not None and agent_id is not None:
            with suppress(Exception):
                await client.remove_participant(room_id, agent_id)
        if agent_id is not None:
            with suppress(Exception):
                await client.delete_agent(agent_id)
        await client.aclose()
