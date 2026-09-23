"""Shared mutations for Band rooms and managed agents."""

from __future__ import annotations

from pathlib import Path

from band_wezterm.client import BandClient, RoomRecord
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.supervisor import ManagedAgentLifecycle
from band_wezterm.supervisor.protocol import WorkerRecord


class RoomOperations:
    """Create and delete rooms through one platform client."""

    def __init__(self, client: BandClient) -> None:
        self._client = client

    async def create(self, title: str) -> RoomRecord:
        return await self._client.create_room(title=title)

    async def delete(self, room_id: str) -> None:
        await self._client.delete_room(room_id)


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
        return await self._lifecycle.start(agent_id, cwd=cwd)

    async def stop(self, agent_id: str) -> WorkerRecord | None:
        return await self._lifecycle.stop(agent_id)

    async def stop_all(self) -> None:
        await self._lifecycle.stop_all()

    async def delete(self, agent_id: str) -> WorkerRecord | None:
        worker = await self.stop(agent_id)
        await self._client.delete_agent(agent_id)
        self._profiles.remove(agent_id)
        return worker
