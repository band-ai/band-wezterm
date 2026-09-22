"""Supervisor IPC lifecycle tests."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from band_wezterm.supervisor.protocol import SupervisorRequest, SupervisorState
from band_wezterm.supervisor.runtime import SupervisorServer


async def _request(socket_path: str, request: SupervisorRequest) -> dict[str, object]:
    reader, writer = await asyncio.open_unix_connection(socket_path)
    try:
        writer.write(request.model_dump_json().encode() + b"\n")
        await writer.drain()
        return json.loads(await reader.readline())
    finally:
        writer.close()
        await writer.wait_closed()


def _state_is_ready(state_path: Path) -> bool:
    if not state_path.exists():
        return False
    state = SupervisorState.model_validate_json(state_path.read_text())
    return Path(state.socket_path).exists()


@pytest.mark.asyncio
async def test_supervisor_requires_authenticated_ipc_and_serves_worker_inventory(
    tmp_path: Path,
) -> None:
    state_path = tmp_path / "state" / "supervisor.json"
    server = SupervisorServer(user_id="user-1", state_path=state_path)
    task = asyncio.create_task(server.run())
    try:
        for _ in range(20):
            if await asyncio.to_thread(_state_is_ready, state_path):
                break
            await asyncio.sleep(0.01)
        state = SupervisorState.model_validate_json(state_path.read_text())

        rejected = await _request(
            state.socket_path,
            SupervisorRequest(token="wrong", action="ping"),
        )
        assert rejected["ok"] is False

        inventory = await _request(
            state.socket_path,
            SupervisorRequest(token=state.token, action="list"),
        )
        assert inventory == {"ok": True, "workers": []}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
