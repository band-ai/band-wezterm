"""Detached-worker control endpoint tests."""

from __future__ import annotations

import asyncio
from pathlib import Path
from uuid import uuid4

import pytest

from band_wezterm.agent.runner import WorkerController
from band_wezterm.supervisor.client import supervisor_socket_directory
from band_wezterm.supervisor.protocol import (
    WorkerAction,
    WorkerRequest,
    WorkerResponse,
    WorkerState,
)


async def _request(
    socket_path: Path, token: str, action: WorkerAction
) -> WorkerResponse:
    reader, writer = await asyncio.open_unix_connection(str(socket_path))
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
    socket_path = supervisor_socket_directory() / f"test-{uuid4().hex}.sock"
    controller = WorkerController(socket_path, "secret")
    await controller.start()
    controller.mark_running()
    try:
        rejected = await _request(socket_path, "wrong", WorkerAction.STATUS)
        assert rejected.ok is False

        running = await _request(socket_path, "secret", WorkerAction.STATUS)
        assert running.state is WorkerState.RUNNING

        stopping = await _request(socket_path, "secret", WorkerAction.STOP)
        assert stopping.state is WorkerState.STOPPING
        assert controller.stop_requested.is_set()
    finally:
        await controller.close()
