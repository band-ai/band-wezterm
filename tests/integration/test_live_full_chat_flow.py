"""Opt-in live: full agent + room + multi-turn human/agent chat.

Covers register → create room → add participant → start harness runtime →
human @mentions → agent replies → history shows both sides. Self-skips without
``BAND_API_KEY_USER`` / harness extras (same ``.env.test`` gate as siblings).
"""

from __future__ import annotations

import asyncio
import time
from contextlib import suppress

import pytest

from tests.live_settings import user_api_key

pytestmark = pytest.mark.live_platform

REPLY_WAIT_SECONDS = 180.0
POLL_SECONDS = 2.0
RUNTIME_WARMUP_SECONDS = 3.0

TURN_ONE_PROMPT = "Reply with exactly: band-wezterm-turn-one"
TURN_ONE_TOKEN = "band-wezterm-turn-one"
TURN_TWO_PROMPT = "Reply with exactly: band-wezterm-turn-two"
TURN_TWO_TOKEN = "band-wezterm-turn-two"


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


def _contents(messages: list) -> list[str]:
    return [(message.content or "") for message in messages]


def _has_token(messages: list, token: str, *, excluding: str) -> bool:
    needle = token.lower()
    exclude = excluding.lower()
    for message in messages:
        content = (message.content or "").lower()
        if needle in content and exclude not in content:
            return True
    return False


def _authored_by(messages: list, name: str) -> list:
    target = name.lower()
    return [
        message
        for message in messages
        if message.author_name and target in message.author_name.lower()
    ]


async def _wait_for(
    client,
    room_id: str,
    *,
    token: str,
    excluding: str,
    agent_name: str,
) -> list:
    deadline = time.monotonic() + REPLY_WAIT_SECONDS
    last: list = []
    while time.monotonic() < deadline:
        last = await client.list_messages(room_id)
        if _has_token(last, token, excluding=excluding):
            return last
        if any(
            TURN_ONE_PROMPT not in (m.content or "")
            and TURN_TWO_PROMPT not in (m.content or "")
            for m in _authored_by(last, agent_name)
        ) and _has_token(last, token, excluding=excluding):
            return last
        await asyncio.sleep(POLL_SECONDS)
    return last


@pytest.mark.asyncio
async def test_live_full_chat_agent_and_human_round_trips() -> None:
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
    stamp = int(time.time())
    agent_name = f"wezterm-chat-{stamp}"
    room_title = f"band-wezterm-full-chat-{stamp}"

    try:
        human_id = await client.whoami()
        assert human_id

        record = await client.create_agent(
            name=agent_name,
            description="band-wezterm full chat live flow",
            harness=harness,
        )
        agent_id = record.id
        managed = client.managed_agent_api_key(agent_id)
        assert managed, "create_agent must persist the one-time managed API key"

        listed = await client.list_my_agents(name=agent_name)
        assert any(agent.id == agent_id for agent in listed)

        room = await client.create_room(title=room_title)
        room_id = room.id
        rooms = await client.list_my_chats()
        assert any(item.id == room_id for item in rooms)

        await client.add_participant(room_id, agent_id)
        roster = await client.list_participants(room_id)
        assert any(participant.id == agent_id for participant in roster)

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
        await asyncio.sleep(RUNTIME_WARMUP_SECONDS)

        human_one = await client.send_message(
            room_id,
            TURN_ONE_PROMPT,
            mention_id=agent_id,
            mention_name=record.name,
        )
        assert human_one.id

        after_one = await _wait_for(
            client,
            room_id,
            token=TURN_ONE_TOKEN,
            excluding=TURN_ONE_PROMPT,
            agent_name=record.name,
        )
        assert _has_token(
            after_one, TURN_ONE_TOKEN, excluding=TURN_ONE_PROMPT
        ), f"Agent never replied to turn one. Messages: {_contents(after_one)}"
        assert any(TURN_ONE_PROMPT in (m.content or "") for m in after_one)

        human_two = await client.send_message(
            room_id,
            TURN_TWO_PROMPT,
            mention_id=agent_id,
            mention_name=record.name,
        )
        assert human_two.id

        after_two = await _wait_for(
            client,
            room_id,
            token=TURN_TWO_TOKEN,
            excluding=TURN_TWO_PROMPT,
            agent_name=record.name,
        )
        assert _has_token(
            after_two, TURN_TWO_TOKEN, excluding=TURN_TWO_PROMPT
        ), f"Agent never replied to turn two. Messages: {_contents(after_two)}"

        history = await client.list_messages(room_id)
        contents = _contents(history)
        assert any(TURN_ONE_PROMPT in body for body in contents), contents
        assert any(TURN_TWO_PROMPT in body for body in contents), contents
        assert _has_token(history, TURN_ONE_TOKEN, excluding=TURN_ONE_PROMPT)
        assert _has_token(history, TURN_TWO_TOKEN, excluding=TURN_TWO_PROMPT)

        agent_msgs = _authored_by(history, record.name)
        assert agent_msgs, f"No messages authored by agent {record.name!r}: {contents}"

        await client.remove_participant(room_id, agent_id)
        roster_after = await client.list_participants(room_id)
        assert all(participant.id != agent_id for participant in roster_after)
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
