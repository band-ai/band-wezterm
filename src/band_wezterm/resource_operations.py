"""Shared mutations for Band rooms and managed agents."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from band_wezterm.client import BandClient, RoomRecord
from band_wezterm.diagnostics import log_event
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.supervisor import ManagedAgentLifecycle
from band_wezterm.supervisor.protocol import WorkerRecord


class ResourceEvent(StrEnum):
    """Safe lifecycle events recorded for CLI and TUI operations."""

    ROOM_CREATE_REQUESTED = "room create requested"
    ROOM_CREATED = "room created"
    ROOM_CREATE_FAILED = "room create failed"
    ROOM_DELETE_REQUESTED = "room delete requested"
    ROOM_DELETED = "room deleted"
    ROOM_DELETE_FAILED = "room delete failed"
    AGENT_START_REQUESTED = "agent start requested"
    AGENT_STARTED = "agent started"
    AGENT_START_FAILED = "agent start failed"
    AGENT_STOP_REQUESTED = "agent stop requested"
    AGENT_STOPPED = "agent stopped"
    AGENT_STOP_FAILED = "agent stop failed"
    AGENTS_STOP_ALL_REQUESTED = "all agents stop requested"
    AGENTS_STOPPED = "all agents stopped"
    AGENTS_STOP_ALL_FAILED = "all agents stop failed"
    AGENT_DELETE_REQUESTED = "agent delete requested"
    AGENT_DELETED = "agent deleted"
    AGENT_DELETE_FAILED = "agent delete failed"


def _error_context(error: BaseException) -> dict[str, str]:
    return {"error_type": type(error).__name__}


class RoomOperations:
    """Create and delete rooms through one platform client."""

    def __init__(self, client: BandClient) -> None:
        self._client = client

    async def create(self, title: str) -> RoomRecord:
        log_event(ResourceEvent.ROOM_CREATE_REQUESTED)
        try:
            room = await self._client.create_room(title=title)
        except Exception as error:
            log_event(ResourceEvent.ROOM_CREATE_FAILED, **_error_context(error))
            raise
        log_event(ResourceEvent.ROOM_CREATED, room_id=room.id)
        return room

    async def delete(self, room_id: str) -> None:
        log_event(ResourceEvent.ROOM_DELETE_REQUESTED, room_id=room_id)
        try:
            await self._client.delete_room(room_id)
        except Exception as error:
            log_event(
                ResourceEvent.ROOM_DELETE_FAILED,
                room_id=room_id,
                **_error_context(error),
            )
            raise
        log_event(ResourceEvent.ROOM_DELETED, room_id=room_id)


class ManagedAgentOperations:
    """Operate detached workers and their durable local profiles."""

    def __init__(
        self,
        client: BandClient,
        lifecycle: ManagedAgentLifecycle,
        profiles: ManagedAgentStore,
    ) -> None:
        self._client = client
        self._lifecycle = lifecycle
        self._profiles = profiles

    async def start(self, agent_id: str, *, cwd: Path) -> WorkerRecord:
        log_event(ResourceEvent.AGENT_START_REQUESTED, agent_id=agent_id)
        try:
            worker = await self._lifecycle.start(agent_id, cwd=cwd)
        except Exception as error:
            log_event(
                ResourceEvent.AGENT_START_FAILED,
                agent_id=agent_id,
                **_error_context(error),
            )
            raise
        log_event(
            ResourceEvent.AGENT_STARTED,
            agent_id=agent_id,
            state=worker.state.value,
        )
        return worker

    async def stop(self, agent_id: str) -> WorkerRecord | None:
        log_event(ResourceEvent.AGENT_STOP_REQUESTED, agent_id=agent_id)
        try:
            worker = await self._lifecycle.stop(agent_id)
        except Exception as error:
            log_event(
                ResourceEvent.AGENT_STOP_FAILED,
                agent_id=agent_id,
                **_error_context(error),
            )
            raise
        log_event(
            ResourceEvent.AGENT_STOPPED,
            agent_id=agent_id,
            state="already_stopped" if worker is None else worker.state.value,
        )
        return worker

    async def stop_all(self) -> None:
        log_event(ResourceEvent.AGENTS_STOP_ALL_REQUESTED)
        try:
            await self._lifecycle.stop_all()
        except Exception as error:
            log_event(ResourceEvent.AGENTS_STOP_ALL_FAILED, **_error_context(error))
            raise
        log_event(ResourceEvent.AGENTS_STOPPED)

    async def delete(self, agent_id: str) -> WorkerRecord | None:
        log_event(ResourceEvent.AGENT_DELETE_REQUESTED, agent_id=agent_id)
        try:
            worker = await self.stop(agent_id)
            await self._client.delete_agent(agent_id)
            self._profiles.remove(agent_id)
        except Exception as error:
            log_event(
                ResourceEvent.AGENT_DELETE_FAILED,
                agent_id=agent_id,
                **_error_context(error),
            )
            raise
        log_event(ResourceEvent.AGENT_DELETED, agent_id=agent_id)
        return worker
