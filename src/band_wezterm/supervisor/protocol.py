"""Authenticated local IPC models for the Band runtime supervisor."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class WorkerState(StrEnum):
    """A managed worker's observable lifecycle state."""

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"


class SupervisorAction(StrEnum):
    """Commands accepted by the per-user supervisor."""

    PING = "ping"
    LIST = "list"
    START = "start"
    STOP = "stop"
    STOP_ALL = "stop_all"


class WorkerAction(StrEnum):
    """Commands accepted by a detached managed worker."""

    STATUS = "status"
    STOP = "stop"


class WorkerRecord(BaseModel):
    """Durable locator for one detached worker process."""

    model_config = ConfigDict(frozen=True)

    agent_id: str
    name: str
    pid: int
    control_socket: str
    control_token: str
    cwd: str
    started_at: float
    state: WorkerState = WorkerState.STARTING


class SupervisorState(BaseModel):
    """The durable, user-private state owned by one supervisor."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    token: str
    socket_path: str
    workers: dict[str, WorkerRecord] = Field(default_factory=dict)


class SupervisorRequest(BaseModel):
    """One request from a disposable Band home or room surface."""

    model_config = ConfigDict(frozen=True)

    token: str
    action: SupervisorAction
    agent_id: str | None = None
    cwd: str | None = None


class WorkerRequest(BaseModel):
    """One request from the supervisor to its worker."""

    model_config = ConfigDict(frozen=True)

    token: str
    action: WorkerAction


class WorkerResponse(BaseModel):
    """Worker health and lifecycle response."""

    model_config = ConfigDict(frozen=True)

    ok: bool
    state: WorkerState
    error: str | None = None
