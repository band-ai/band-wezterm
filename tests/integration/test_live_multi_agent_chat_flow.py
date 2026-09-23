"""Opt-in live: two managed harness agents share one room and both reply."""

from __future__ import annotations

import time
from contextlib import suppress

import pytest

from band_wezterm.client import BandClient
from band_wezterm.config import load_settings
from tests.live_harness import (
    LiveAgentRuntime,
    message_has_token,
    pick_harness,
    start_agent_runtime,
    stop_agent_runtime,
    wait_for_reply_token,
)
from tests.live_settings import LIVE_SENDER_NAME, user_api_key

pytestmark = pytest.mark.live_platform

FIRST_TOKEN = "band-wezterm-first-agent-reply"
SECOND_TOKEN = "band-wezterm-second-agent-reply"


@pytest.mark.asyncio
async def test_live_two_harness_agents_share_a_room() -> None:
    api_key = user_api_key()
    if not api_key:
        pytest.skip("BAND_API_KEY_USER not set (see .env.test)")
    harness = pick_harness()
    if harness is None:
        pytest.skip("No harness adapter extra installed (uv sync --extra agents)")

    settings = load_settings()
    client = BandClient.from_user_api_key(api_key, settings)
    sessions: list[LiveAgentRuntime] = []
    agent_ids: list[str] = []
    room_id: str | None = None
    stamp = int(time.time())
    try:
        records = []
        for suffix in ("first", "second"):
            record = await client.create_agent(
                name=f"wezterm-pair-{suffix}-{stamp}",
                description="band-wezterm live multi-agent chat flow",
            )
            managed_key = client.managed_agent_api_key(record.id)
            assert managed_key, "create_agent must persist the managed API key"
            records.append(record)
            agent_ids.append(record.id)

        room = await client.create_room(title=f"band-wezterm-pair-{stamp}")
        room_id = room.id
        for record in records:
            await client.add_participant(room_id, record.id)

        for record in records:
            managed_key = client.managed_agent_api_key(record.id)
            assert managed_key
            sessions.append(
                await start_agent_runtime(
                    harness=harness,
                    agent_id=record.id,
                    api_key=managed_key,
                    rest_url=settings.band_base_url,
                    ws_url=settings.band_ws_url,
                )
            )

        for record, token in zip(records, (FIRST_TOKEN, SECOND_TOKEN), strict=True):
            prompt = f"Reply with exactly: {token}"
            await client.send_message(
                room_id,
                prompt,
                mentions=[(record.id, record.name)],
                sender_name=LIVE_SENDER_NAME,
            )
            messages = await wait_for_reply_token(
                client, room_id, token=token, excluding=prompt
            )
            assert message_has_token(messages, token, excluding=prompt)
            assert any(
                record.name.lower() in message.author_name.lower()
                for message in messages
            )
    finally:
        for session in reversed(sessions):
            await stop_agent_runtime(session)
        if room_id is not None:
            for agent_id in agent_ids:
                with suppress(Exception):
                    await client.remove_participant(room_id, agent_id)
        for agent_id in agent_ids:
            with suppress(Exception):
                await client.delete_agent(agent_id)
        await client.aclose()
