"""Shared helpers for opt-in live harness tests."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from contextlib import suppress
from typing import Any

from band import Agent
from band.runtime.types import AgentConfig

from band_wezterm.agent.adapters import (
    HarnessUnavailableError,
    build_adapter,
    preflight_harness,
)
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
) -> tuple[Any, asyncio.Task[None]]:
    adapter = build_adapter(harness)
    runtime = Agent.create(
        adapter=adapter,
        agent_id=agent_id,
        api_key=api_key,
        rest_url=rest_url,
        ws_url=ws_url,
        config=AgentConfig(auto_subscribe_existing_rooms=True, single_instance=True),
    )
    await runtime.__aenter__()
    task = asyncio.create_task(runtime.run_forever())
    await asyncio.sleep(RUNTIME_WARMUP_SECONDS)
    return runtime, task


async def stop_agent_runtime(
    runtime: Any | None, task: asyncio.Task[None] | None
) -> None:
    if task is not None:
        task.cancel()
        with suppress(asyncio.CancelledError, Exception):
            await task
    if runtime is not None:
        with suppress(Exception):
            await runtime.__aexit__(None, None, None)
