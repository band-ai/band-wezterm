"""Detached-worker control endpoint tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

import band_wezterm.agent.runner as runner
from band_wezterm.agent.runner import WorkerController, parse_args
from band_wezterm.supervisor.client import supervisor_socket_directory
from band_wezterm.supervisor.ipc import new_endpoint, open_connection
from band_wezterm.supervisor.protocol import (
    WorkerAction,
    WorkerRequest,
    WorkerResponse,
    WorkerState,
)


async def _request(
    socket_path: str, token: str, action: WorkerAction
) -> WorkerResponse:
    reader, writer = await open_connection(socket_path)
    try:
        writer.write(
            WorkerRequest(token=token, action=action).model_dump_json().encode() + b"\n"
        )
        await writer.drain()
        return WorkerResponse.model_validate_json(await reader.readline())
    finally:
        writer.close()
        await writer.wait_closed()


@pytest.mark.asyncio
async def test_worker_controller_authenticates_and_requests_graceful_stop() -> None:
    socket_path = new_endpoint(supervisor_socket_directory(), f"test-{uuid4().hex}.sock")
    controller = WorkerController(socket_path, "secret")
    await controller.start()
    controller.mark_running()
    try:
        assert controller.endpoint is not None
        socket_path = controller.endpoint
        rejected = await _request(socket_path, "wrong", WorkerAction.STATUS)
        assert rejected.ok is False

        running = await _request(socket_path, "secret", WorkerAction.STATUS)
        assert running.state is WorkerState.RUNNING

        stopping = await _request(socket_path, "secret", WorkerAction.STOP)
        assert stopping.state is WorkerState.STOPPING
        assert controller.stop_requested.is_set()
    finally:
        await controller.close()


@pytest.mark.asyncio
async def test_worker_controller_accepts_the_socket_value_from_runner_arguments() -> None:
    socket_path = new_endpoint(supervisor_socket_directory(), f"test-{uuid4().hex}.sock")
    args = parse_args(["--control-socket", socket_path, "--control-token", "secret"])
    controller = WorkerController(args.control_socket, args.control_token)
    await controller.start()
    try:
        assert controller.endpoint is not None
        response = await _request(controller.endpoint, "secret", WorkerAction.STATUS)
        assert response.state is WorkerState.STARTING
    finally:
        await controller.close()


@pytest.mark.asyncio
async def test_runner_rejects_an_agent_without_an_identity(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert await runner.run(parse_args([])) == 2
    assert "--agent-id is required" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_runner_stops_a_live_agent_and_removes_its_one_time_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    key_file = tmp_path / "agent-key"
    key_file.write_text("agent-key", encoding="utf-8")
    agent = _StoppingAgent()
    controller = _StoppingController()
    create_agent = MagicMock(return_value=agent)
    build = MagicMock(return_value=object())

    monkeypatch.setattr(runner, "WorkerController", lambda *_args: controller)
    monkeypatch.setattr(runner, "build_adapter", build)
    monkeypatch.setattr(runner.Agent, "create", create_agent)
    monkeypatch.setattr(
        runner,
        "load_settings",
        lambda: SimpleNamespace(
            band_base_url="https://api.example.test",
            band_ws_url="wss://api.example.test",
        ),
    )
    monkeypatch.setattr(runner, "announce_agent_pane", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(runner, "announce_runtime_status", lambda _status: None)
    monkeypatch.setattr(runner, "log_event", lambda *_args, **_kwargs: None)

    args = parse_args(
        [
            "--agent-id",
            "agent-1",
            "--harness",
            "codex",
            "--name",
            "Architect",
            "--key-file",
            str(key_file),
            "--cwd",
            str(tmp_path),
        ]
    )

    assert await runner.run(args) == 0
    assert not key_file.exists()
    assert agent.stopped
    assert controller.closed
    build.assert_called_once()
    create_agent.assert_called_once()
    assert "Online — listening to Band rooms" in capsys.readouterr().out


class _StoppingAgent:
    def __init__(self) -> None:
        self._stopped = asyncio.Event()

    async def __aenter__(self) -> _StoppingAgent:
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def run_forever(self) -> None:
        await self._stopped.wait()

    async def stop(self) -> None:
        self._stopped.set()

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set()


class _StoppingController:
    def __init__(self) -> None:
        self.stop_requested = asyncio.Event()
        self.stop_requested.set()
        self.closed = False

    async def start(self) -> None:
        return None

    def mark_running(self) -> None:
        return None

    def mark_error(self) -> None:
        return None

    async def close(self) -> None:
        self.closed = True
