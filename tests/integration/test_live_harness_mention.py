"""Opt-in live: start one harness runtime, @mention, assert a reply.

Skips without ``BAND_API_KEY_USER``, without a usable harness extra, or when
the harness host CLI/auth is absent. Same ``.env.test`` gate as other live tests.
"""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress

import pytest

from tests.live_settings import user_api_key

pytestmark = pytest.mark.live_platform

REPLY_WAIT_SECONDS = 120.0
POLL_SECONDS = 2.0
MENTION_PROMPT = "Reply with exactly: band-wezterm-harness-ok"
REPLY_TOKEN = "band-wezterm-harness-ok"


def _pick_harness():
    from band_wezterm.agent.adapters import HarnessUnavailableError, preflight_harness
    from band_wezterm.identity import HarnessId

    for harness in (
        HarnessId.CLAUDE_SDK,
        HarnessId.CODEX,
        HarnessId.COPILOT_SDK,
        HarnessId.OPENCODE,
    ):
        try:
            preflight_harness(harness)
        except HarnessUnavailableError:
            continue
        return harness
    return None


@pytest.mark.asyncio
async def test_live_harness_mention_gets_reply() -> None:
    from band import Agent
    from band.runtime.types import AgentConfig

    from band_wezterm.agent.adapters import build_adapter
    from band_wezterm.client import BandClient
    from band_wezterm.config import load_settings

    api_key = user_api_key()
    if not api_key:
        pytest.skip("BAND_API_KEY_USER not set (see .env.test)")

    harness = _pick_harness()
    if harness is None:
        pytest.skip("No harness adapter extra installed (uv sync --extra agents)")

    settings = load_settings()
    client = BandClient.from_user_api_key(api_key, settings)
    agent_runtime = None
    room_id = None
    agent_id = None
    run_task = None
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

        adapter = build_adapter(harness)
        agent_runtime = Agent.create(
            adapter=adapter,
            agent_id=agent_id,
            api_key=managed,
            rest_url=settings.band_base_url,
            ws_url=settings.band_ws_url,
            config=AgentConfig(
                auto_subscribe_existing_rooms=True, single_instance=True
            ),
        )
        await agent_runtime.__aenter__()
        run_task = asyncio.create_task(agent_runtime.run_forever())

        await client.send_message(
            room_id,
            MENTION_PROMPT,
            mention_id=agent_id,
            mention_name=record.name,
        )

        deadline = time.monotonic() + REPLY_WAIT_SECONDS
        found = False
        while time.monotonic() < deadline:
            messages = await client.list_messages(room_id)
            for message in messages:
                content = (message.content or "").lower()
                if REPLY_TOKEN in content and MENTION_PROMPT.lower() not in content:
                    found = True
                    break
                if (
                    message.author_name
                    and record.name.lower() in message.author_name.lower()
                    and MENTION_PROMPT not in (message.content or "")
                ):
                    found = True
                    break
            if found:
                break
            await asyncio.sleep(POLL_SECONDS)

        assert found, "Timed out waiting for harness agent reply to @mention"
    finally:
        if run_task is not None:
            run_task.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await run_task
        if agent_runtime is not None:
            with suppress(Exception):
                await agent_runtime.__aexit__(None, None, None)
        if room_id is not None and agent_id is not None:
            with suppress(Exception):
                await client.remove_participant(room_id, agent_id)
        if agent_id is not None:
            with suppress(Exception):
                await client.delete_agent(agent_id)
        await client.aclose()
