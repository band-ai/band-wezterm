"""Supervisor IPC lifecycle tests."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from band_wezterm.supervisor.client import SupervisorClient
from band_wezterm.supervisor.ipc import is_tcp, open_connection
from band_wezterm.supervisor.protocol import (
    SupervisorAction,
    SupervisorRequest,
    SupervisorState,
    WorkerRecord,
    WorkerState,
)
from band_wezterm.supervisor.runtime import SupervisorServer


async def _request(socket_path: str, request: SupervisorRequest) -> dict[str, object]:
    reader, writer = await open_connection(socket_path)
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
    return is_tcp(state.socket_path) or Path(state.socket_path).exists()


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
            SupervisorRequest(token="wrong", action=SupervisorAction.PING),
        )
        assert rejected["ok"] is False

        inventory = await _request(
            state.socket_path,
            SupervisorRequest(token=state.token, action=SupervisorAction.LIST),
        )
        assert inventory == {"ok": True, "workers": []}
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_supervisor_serializes_concurrent_lifecycle_requests(
    tmp_path: Path,
) -> None:
    server = SupervisorServer(user_id="user-1", state_path=tmp_path / "state.json")
    active = 0
    maximum = 0

    async def start(_agent_id: str, _cwd: Path) -> WorkerRecord:
        nonlocal active, maximum
        active += 1
        maximum = max(maximum, active)
        await asyncio.sleep(0)
        active -= 1
        return WorkerRecord(
            agent_id="agent-1",
            name="Agent",
            pid=1,
            control_socket="/tmp/worker.sock",
            control_token="token",
            cwd=str(tmp_path),
            started_at=0,
        )

    server._start_worker = start  # type: ignore[method-assign]
    request = SupervisorRequest(
        token="token",
        action=SupervisorAction.START,
        agent_id="agent-1",
        cwd=str(tmp_path),
    )
    await asyncio.gather(server._dispatch(request), server._dispatch(request))

    assert maximum == 1


@pytest.mark.asyncio
async def test_client_starts_one_supervisor_for_concurrent_connects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = SupervisorClient()
    started: list[str] = []
    monkeypatch.setattr(
        "band_wezterm.supervisor.client.supervisor_state_path",
        lambda _user_id, _settings: tmp_path / "supervisor.json",
    )

    async def healthy() -> bool:
        return bool(started)

    async def ready() -> None:
        await asyncio.sleep(0)

    monkeypatch.setattr(client, "_is_healthy", healthy)
    monkeypatch.setattr(client, "_wait_until_ready", ready)
    monkeypatch.setattr(
        client, "_start_supervisor", lambda user_id, _path: started.append(user_id)
    )

    await asyncio.gather(client.connect("user-1"), client.connect("user-1"))

    assert started == ["user-1"]


@pytest.mark.asyncio
async def test_stop_of_unready_worker_terminates_its_process_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = WorkerRecord(
        agent_id="agent-1",
        name="Agent",
        pid=os.getpid(),
        control_socket=str(tmp_path / "missing.sock"),
        control_token="token",
        cwd=str(tmp_path),
        started_at=0,
    )
    server = SupervisorServer(user_id="user-1", state_path=tmp_path / "state.json")
    server._state = server._state.model_copy(
        update={"workers": {worker.agent_id: worker}}
    )
    server._save_state = MagicMock()  # type: ignore[method-assign]
    terminated: list[int] = []
    monkeypatch.setattr("band_wezterm.supervisor.runtime.WORKER_START_GRACE_SECONDS", 0)
    monkeypatch.setattr(
        "band_wezterm.supervisor.runtime._terminate_worker", terminated.append
    )

    result = await server._stop_worker(worker.agent_id)

    assert result is None
    assert server._state.workers == {}
    assert terminated == [worker.pid]


@pytest.mark.asyncio
async def test_refresh_force_stops_an_unresponsive_stopping_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = WorkerRecord(
        agent_id="agent-1",
        name="Agent",
        pid=1,
        control_socket=str(tmp_path / "missing.sock"),
        control_token="token",
        cwd=str(tmp_path),
        started_at=0,
        state=WorkerState.STOPPING,
        stopping_at=0,
    )
    server = SupervisorServer(user_id="user-1", state_path=tmp_path / "state.json")
    server._state = server._state.model_copy(
        update={"workers": {worker.agent_id: worker}}
    )
    server._save_state = MagicMock()  # type: ignore[method-assign]
    terminated: list[int] = []
    monkeypatch.setattr("band_wezterm.supervisor.runtime._pid_alive", lambda _pid: True)
    monkeypatch.setattr(
        "band_wezterm.supervisor.runtime._terminate_worker", terminated.append
    )

    workers = await server._refresh_workers()

    assert workers == ()
    assert server._state.workers == {}
    assert terminated == [worker.pid]


def test_restarted_supervisor_adopts_persisted_worker_state(tmp_path: Path) -> None:
    state_path = tmp_path / "state.json"
    worker = WorkerRecord(
        agent_id="agent-1",
        name="Agent",
        pid=1,
        control_socket="/tmp/worker.sock",
        control_token="token",
        cwd=str(tmp_path),
        started_at=0,
        state=WorkerState.RUNNING,
    )
    state = SupervisorState(
        user_id="user-1",
        token="supervisor-token",
        socket_path="/tmp/old.sock",
        workers={worker.agent_id: worker},
    )
    state_path.write_text(state.model_dump_json())

    server = SupervisorServer(user_id="user-1", state_path=state_path)
    server._load_or_create_state()

    assert server._state.workers == {worker.agent_id: worker}
