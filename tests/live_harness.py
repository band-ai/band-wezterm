"""Shared helpers for opt-in live harness tests."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from band import Agent
from band.runtime.types import AgentConfig

from band_wezterm.agent.adapters import (
    HarnessUnavailableError,
    build_adapter,
    preflight_harness,
)
from band_wezterm.agent.opencode_server import OpenCodeServerManager
from band_wezterm.client import BandClient, MessageRecord
from band_wezterm.identity import HarnessId

REPLY_WAIT_SECONDS = 180.0
POLL_SECONDS = 2.0
RUNTIME_WARMUP_SECONDS = 3.0

_HARNESS_PREFERENCE: tuple[HarnessId, ...] = (
    HarnessId.CLAUDE_SDK,
    HarnessId.CODEX,
    HarnessId.COPILOT_SDK,
    HarnessId.OPENCODE,
)

LIVE_HARNESSES = _HARNESS_PREFERENCE


@dataclass
class LiveAgentRuntime:
    """One live SDK runtime and the local service it may require."""

    runtime: Any
    task: asyncio.Task[None]
    opencode_server: OpenCodeServerManager | None = None


def pick_harness() -> HarnessId | None:
    for harness in _HARNESS_PREFERENCE:
        try:
            preflight_harness(harness)
        except HarnessUnavailableError:
            continue
        return harness
    return None


def message_has_token(
    messages: Sequence[MessageRecord], token: str, *, excluding: str
) -> bool:
    needle = token.lower()
    exclude = excluding.lower()
    return any(
        needle in (message.content or "").lower()
        and exclude not in (message.content or "").lower()
        for message in messages
    )


async def wait_for_reply_token(
    client: BandClient,
    room_id: str,
    *,
    token: str,
    excluding: str,
) -> list[MessageRecord]:
    deadline = time.monotonic() + REPLY_WAIT_SECONDS
    last: list[MessageRecord] = []
    while time.monotonic() < deadline:
        last = await client.list_messages(room_id)
        if message_has_token(last, token, excluding=excluding):
            return last
        await asyncio.sleep(POLL_SECONDS)
    return last


async def start_agent_runtime(
    *,
    harness: HarnessId,
    agent_id: str,
    api_key: str,
    rest_url: str,
    ws_url: str,
) -> LiveAgentRuntime:
    opencode_server = OpenCodeServerManager() if harness is HarnessId.OPENCODE else None
    try:
        opencode_server_url = None
        if opencode_server is not None:
            opencode_server_url = (await opencode_server.ensure()).url
        runtime = Agent.create(
            adapter=build_adapter(harness, opencode_server_url=opencode_server_url),
            agent_id=agent_id,
            api_key=api_key,
            rest_url=rest_url,
            ws_url=ws_url,
            config=AgentConfig(
                auto_subscribe_existing_rooms=True,
                single_instance=True,
            ),
        )
        await runtime.__aenter__()
        task = asyncio.create_task(runtime.run_forever())
        await asyncio.sleep(RUNTIME_WARMUP_SECONDS)
    except Exception:
        if opencode_server is not None:
            await opencode_server.close()
        raise
    return LiveAgentRuntime(runtime, task, opencode_server)


async def stop_agent_runtime(session: LiveAgentRuntime | None) -> None:
    if session is None:
        return
    session.task.cancel()
    with suppress(asyncio.CancelledError, Exception):
        await session.task
    with suppress(Exception):
        await session.runtime.__aexit__(None, None, None)
    if session.opencode_server is not None:
        with suppress(asyncio.CancelledError, Exception):
            await session.opencode_server.close()
