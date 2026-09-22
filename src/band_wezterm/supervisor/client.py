"""Client for the durable local runtime supervisor."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path
from typing import Final

from filelock import FileLock
from pydantic import ValidationError

from band_wezterm.config import LOCAL_STATE_DIRNAME
from band_wezterm.supervisor.protocol import (
    SupervisorAction,
    SupervisorRequest,
    SupervisorState,
    WorkerRecord,
)

SUPERVISOR_DIRNAME: Final = "supervisors"
SUPERVISOR_SOCKET_DIRNAME: Final = "band-wezterm-runtime"
SUPERVISOR_LOCK_TIMEOUT_SECONDS: Final = 10
SUPERVISOR_START_TIMEOUT_SECONDS: Final = 5
SUPERVISOR_RETRY_SECONDS: Final = 0.05


class SupervisorError(RuntimeError):
    """The local supervisor is unavailable or rejected a request."""


def supervisor_directory() -> Path:
    return Path.home() / LOCAL_STATE_DIRNAME / SUPERVISOR_DIRNAME


def supervisor_state_path(user_id: str) -> Path:
    """Stable short filename for a user id without leaking it in a path."""
    digest = hashlib.sha256(user_id.encode()).hexdigest()
    return supervisor_directory() / f"{digest}.json"


def supervisor_socket_directory() -> Path:
    """Short user-private path; macOS limits Unix-domain socket names tightly."""
    directory = Path("/tmp") / f"{SUPERVISOR_SOCKET_DIRNAME}-{os.getuid()}"
    directory.mkdir(mode=0o700, exist_ok=True)
    metadata = os.lstat(directory)
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid():
        raise SupervisorError("Band runtime socket directory is unsafe.")
    directory.chmod(0o700)
    return directory


class SupervisorClient:
    """Authenticate a Control surface to one per-user detached supervisor."""

    def __init__(self, user_id: str | None = None) -> None:
        self._user_id = user_id
        self._state_path = supervisor_state_path(user_id) if user_id else None

    @property
    def user_id(self) -> str | None:
        return self._user_id

    async def connect(self, user_id: str) -> None:
        """Adopt a healthy supervisor or atomically start one."""
        if self._user_id == user_id and await self._is_healthy():
            return
        self._user_id = user_id
        self._state_path = supervisor_state_path(user_id)
        state_path = self._state_path
        state_path.parent.mkdir(parents=True, exist_ok=True)
        lock = FileLock(
            str(state_path.with_suffix(".lock")),
            timeout=SUPERVISOR_LOCK_TIMEOUT_SECONDS,
        )
        with lock:
            if await self._is_healthy():
                return
            self._start_supervisor(user_id, state_path)
            await self._wait_until_ready()

    async def list_workers(self) -> tuple[WorkerRecord, ...]:
        payload = await self._request(SupervisorAction.LIST)
        workers = payload.get("workers", [])
        try:
            return tuple(WorkerRecord.model_validate(worker) for worker in workers)
        except ValidationError as error:
            raise SupervisorError(
                f"Supervisor returned invalid worker state: {error}"
            ) from error

    async def start(self, agent_id: str, *, cwd: Path) -> WorkerRecord:
        payload = await self._request(
            SupervisorAction.START, agent_id=agent_id, cwd=str(cwd)
        )
        try:
            return WorkerRecord.model_validate(payload["worker"])
        except (KeyError, ValidationError) as error:
            raise SupervisorError(
                f"Supervisor returned invalid started worker: {error}"
            ) from error

    async def stop(self, agent_id: str) -> WorkerRecord | None:
        payload = await self._request(SupervisorAction.STOP, agent_id=agent_id)
        worker = payload.get("worker")
        if worker is None:
            return None
        try:
            return WorkerRecord.model_validate(worker)
        except ValidationError as error:
            raise SupervisorError(
                f"Supervisor returned invalid stopping worker: {error}"
            ) from error

    async def stop_all(self) -> None:
        await self._request(SupervisorAction.STOP_ALL)

    async def _is_healthy(self) -> bool:
        try:
            await self._request(SupervisorAction.PING)
        except SupervisorError:
            return False
        return True

    def _start_supervisor(self, user_id: str, state_path: Path) -> None:
        subprocess.Popen(
            [
                sys.executable,
                "-m",
                "band_wezterm.supervisor",
                "--user-id",
                user_id,
                "--state-path",
                str(state_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )

    async def _wait_until_ready(self) -> None:
        deadline = time.monotonic() + SUPERVISOR_START_TIMEOUT_SECONDS
        while time.monotonic() < deadline:
            if await self._is_healthy():
                return
            await asyncio.sleep(SUPERVISOR_RETRY_SECONDS)
        raise SupervisorError("Band runtime supervisor did not start in time.")

    def _state(self) -> SupervisorState:
        path = self._state_path
        if path is None:
            raise SupervisorError("Band runtime supervisor is not connected.")
        try:
            return SupervisorState.model_validate_json(path.read_text(encoding="utf-8"))
        except (OSError, ValidationError) as error:
            raise SupervisorError(
                "Band runtime supervisor state is unavailable."
            ) from error

    async def _request(
        self,
        action: SupervisorAction,
        *,
        agent_id: str | None = None,
        cwd: str | None = None,
    ) -> dict[str, object]:
        try:
            state = self._state()
            request = SupervisorRequest(
                token=state.token,
                action=action,
                agent_id=agent_id,
                cwd=cwd,
            )
            reader, writer = await asyncio.open_unix_connection(state.socket_path)
            try:
                writer.write(request.model_dump_json().encode() + b"\n")
                await writer.drain()
                line = await asyncio.wait_for(
                    reader.readline(), timeout=SUPERVISOR_START_TIMEOUT_SECONDS
                )
            finally:
                writer.close()
                await writer.wait_closed()
        except (TimeoutError, OSError) as error:
            raise SupervisorError("Band runtime supervisor is unavailable.") from error
        if not line:
            raise SupervisorError("Band runtime supervisor closed the connection.")
        try:
            payload = json.loads(line)
        except ValueError as error:
            raise SupervisorError(
                "Band runtime supervisor sent invalid JSON."
            ) from error
        if not isinstance(payload, dict) or not payload.get("ok"):
            detail = (
                payload.get("error") if isinstance(payload, dict) else "unknown error"
            )
            raise SupervisorError(f"Band runtime supervisor: {detail}")
        return payload
