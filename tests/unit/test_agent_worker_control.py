"""Detached-worker control endpoint tests."""

from __future__ import annotations

from uuid import uuid4

import pytest

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
