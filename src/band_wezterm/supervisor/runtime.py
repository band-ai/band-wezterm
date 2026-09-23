"""Detached process that owns managed-agent worker lifecycle."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from pathlib import Path
from typing import Final
from uuid import uuid4

from pydantic import ValidationError

from band_wezterm.auth.credentials import ManagedAgentKeyStore
from band_wezterm.diagnostics import configure_diagnostics, log_event
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.supervisor.client import supervisor_socket_directory
from band_wezterm.supervisor.ipc import (
    new_endpoint,
    open_connection,
    remove_endpoint,
    start_server,
)
from band_wezterm.supervisor.protocol import (
    SupervisorAction,
    SupervisorRequest,
    SupervisorState,
    WorkerAction,
    WorkerRecord,
    WorkerRequest,
    WorkerResponse,
    WorkerState,
)

SOCKET_MODE: Final = 0o600
STATE_MODE: Final = 0o600
DIRECTORY_MODE: Final = 0o700
IPC_TIMEOUT_SECONDS: Final = 2
WORKER_START_GRACE_SECONDS: Final = 10
WORKER_STOP_RETRY_SECONDS: Final = 0.05


class SupervisorServer:
    """One user-private server that starts and adopts detached workers."""

    def __init__(self, *, user_id: str, state_path: Path) -> None:
        self._user_id = user_id
        self._state_path = state_path
        self._state = self._new_state()
        self._server: asyncio.Server | None = None
        self._lifecycle_lock = asyncio.Lock()

    async def run(self) -> None:
        self._load_or_create_state()
        self._server, endpoint = await start_server(
            self._handle_connection, self._state.socket_path
        )
        self._state = self._state.model_copy(update={"socket_path": endpoint})
        self._save_state()
        if not endpoint.startswith("tcp://"):
            await asyncio.to_thread(Path(endpoint).chmod, SOCKET_MODE)
        try:
            async with self._server:
                await self._server.serve_forever()
        finally:
            await remove_endpoint(self._state.socket_path)

    def _new_state(self) -> SupervisorState:
        socket_path = new_endpoint(supervisor_socket_directory(), f"{uuid4().hex}.sock")
        return SupervisorState(
            user_id=self._user_id,
            token=secrets.token_urlsafe(),
            socket_path=socket_path,
        )

    def _load_or_create_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        with suppress(PermissionError):
            self._state_path.parent.chmod(DIRECTORY_MODE)
        try:
            existing = SupervisorState.model_validate_json(
                self._state_path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError):
            existing = None
        if existing is not None and existing.user_id == self._user_id:
            self._state = existing.model_copy(
                update={"socket_path": self._new_state().socket_path}
            )
        self._save_state()

    def _save_state(self) -> None:
        content = self._state.model_dump_json(indent=2) + "\n"
        fd, temporary = tempfile.mkstemp(
            dir=self._state_path.parent,
            prefix=f".{self._state_path.name}.",
            suffix=".tmp",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary, STATE_MODE)
            os.replace(temporary, self._state_path)
        except Exception:
            Path(temporary).unlink(missing_ok=True)
            raise

    async def _handle_connection(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            line = await reader.readline()
            request = SupervisorRequest.model_validate_json(line)
            if not secrets.compare_digest(request.token, self._state.token):
                raise PermissionError("authentication failed")
            response = await self._dispatch(request)
        except (PermissionError, ValidationError, ValueError) as error:
            response = {"ok": False, "error": str(error)}
        except Exception as error:  # Keep the supervisor reachable after one failure.
            response = {"ok": False, "error": str(error)}
        writer.write(json.dumps(response).encode() + b"\n")
        with suppress(OSError):
            await writer.drain()
        writer.close()
        with suppress(OSError):
            await writer.wait_closed()

    async def _dispatch(self, request: SupervisorRequest) -> dict[str, object]:
        match request.action:
            case SupervisorAction.PING:
                return {"ok": True}
            case SupervisorAction.LIST:
                async with self._lifecycle_lock:
                    workers = await self._refresh_workers()
                return {
                    "ok": True,
                    "workers": [worker.model_dump(mode="json") for worker in workers],
                }
            case SupervisorAction.START if request.agent_id and request.cwd:
                async with self._lifecycle_lock:
                    worker = await self._start_worker(
                        request.agent_id, Path(request.cwd)
                    )
                return {"ok": True, "worker": worker.model_dump(mode="json")}
            case SupervisorAction.STOP if request.agent_id:
                async with self._lifecycle_lock:
                    worker = await self._stop_worker(request.agent_id)
                return {
                    "ok": True,
                    "worker": None
                    if worker is None
                    else worker.model_dump(mode="json"),
                }
            case SupervisorAction.STOP_ALL:
                async with self._lifecycle_lock:
                    await self._stop_all_workers()
                return {"ok": True}
            case _:
                raise ValueError("unsupported supervisor request")

    async def _refresh_workers(self) -> tuple[WorkerRecord, ...]:
        refreshed: dict[str, WorkerRecord] = {}
        for agent_id, worker in self._state.workers.items():
            status = await _worker_request(worker, WorkerAction.STATUS)
            if status is None:
                if _pid_alive(worker.pid) and (
                    worker.state is WorkerState.STARTING
                    and time.time() - worker.started_at < WORKER_START_GRACE_SECONDS
                ):
                    refreshed[agent_id] = worker
                elif worker.state is not WorkerState.STOPPING:
                    refreshed[agent_id] = worker.model_copy(
                        update={"state": WorkerState.ERROR}
                    )
                continue
            refreshed[agent_id] = worker.model_copy(update={"state": status.state})
        if refreshed != self._state.workers:
            self._state = self._state.model_copy(update={"workers": refreshed})
            self._save_state()
        return tuple(refreshed.values())

    async def _start_worker(self, agent_id: str, cwd: Path) -> WorkerRecord:
        workers = {worker.agent_id: worker for worker in await self._refresh_workers()}
        existing = workers.get(agent_id)
        if existing is not None and existing.state in {
            WorkerState.STARTING,
            WorkerState.RUNNING,
            WorkerState.STOPPING,
        }:
            return existing
        profile = ManagedAgentStore().get(agent_id)
        if profile is None:
            raise ValueError(
                "No local profile — register or reconfigure after upgrade."
            )
        if ManagedAgentKeyStore().get(agent_id) is None:
            raise ValueError(
                "No managed API key — re-register this agent from `band agent`."
            )
        control_socket = new_endpoint(
            supervisor_socket_directory(), f"worker-{uuid4().hex}.sock"
        )
        control_token = secrets.token_urlsafe()
        command = [
            sys.executable,
            "-m",
            "band_wezterm.agent",
            "--managed",
            "--agent-id",
            agent_id,
            "--cwd",
            str(cwd),
            "--control-socket",
            control_socket,
            "--control-token",
            control_token,
        ]
        process = await asyncio.to_thread(
            subprocess.Popen,
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        worker = WorkerRecord(
            agent_id=agent_id,
            name=profile.name,
            pid=process.pid,
            control_socket=control_socket,
            control_token=control_token,
            cwd=str(cwd),
            started_at=time.time(),
        )
        workers[agent_id] = worker
        self._state = self._state.model_copy(update={"workers": workers})
        self._save_state()
        return worker

    async def _stop_worker(self, agent_id: str) -> WorkerRecord | None:
        worker = self._state.workers.get(agent_id)
        if worker is None:
            return None
        status = await _request_worker_stop(worker)
        if status is None:
            if _pid_alive(worker.pid):
                _terminate_worker(worker.pid)
            workers = dict(self._state.workers)
            workers.pop(agent_id, None)
        else:
            workers = dict(self._state.workers)
            workers[agent_id] = worker.model_copy(update={"state": status.state})
        self._state = self._state.model_copy(update={"workers": workers})
        self._save_state()
        return workers.get(agent_id)

    async def _stop_all_workers(self) -> None:
        for agent_id in tuple(self._state.workers):
            await self._stop_worker(agent_id)


async def _worker_request(
    worker: WorkerRecord, action: WorkerAction
) -> WorkerResponse | None:
    try:
        reader, writer = await open_connection(worker.control_socket)
        try:
            request = WorkerRequest(token=worker.control_token, action=action)
            writer.write(request.model_dump_json().encode() + b"\n")
            await writer.drain()
            line = await asyncio.wait_for(
                reader.readline(), timeout=IPC_TIMEOUT_SECONDS
            )
        finally:
            writer.close()
            await writer.wait_closed()
        return WorkerResponse.model_validate_json(line)
    except (TimeoutError, OSError, ValidationError):
        return None


async def _request_worker_stop(worker: WorkerRecord) -> WorkerResponse | None:
    """Wait briefly for a freshly spawned worker before force-stopping it."""
    status = await _worker_request(worker, WorkerAction.STOP)
    if status is not None or worker.state is not WorkerState.STARTING:
        return status
    deadline = time.monotonic() + WORKER_START_GRACE_SECONDS
    while _pid_alive(worker.pid) and time.monotonic() < deadline:
        await asyncio.sleep(WORKER_STOP_RETRY_SECONDS)
        status = await _worker_request(worker, WorkerAction.STOP)
        if status is not None:
            return status
    return None


def _terminate_worker(pid: int) -> None:
    """Terminate the detached worker process group after graceful stop fails."""
    with suppress(ProcessLookupError):
        os.killpg(pid, signal.SIGTERM)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="band_wezterm.supervisor")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--state-path", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    configure_diagnostics()
    args = parse_args(argv)
    log_event("supervisor starting")
    asyncio.run(
        SupervisorServer(user_id=args.user_id, state_path=args.state_path).run()
    )
    return 0
