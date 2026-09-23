"""One lifecycle boundary for detached managed-agent workers."""

from __future__ import annotations

from pathlib import Path

from band_wezterm.supervisor.client import SupervisorClient
from band_wezterm.supervisor.protocol import WorkerRecord


class ManagedAgentLifecycle:
    """Start, stop, and observe workers through one authenticated supervisor."""

    def __init__(self, supervisor: SupervisorClient) -> None:
        self._supervisor = supervisor

    async def workers(self) -> tuple[WorkerRecord, ...]:
        return await self._supervisor.list_workers()

    async def start(self, agent_id: str, *, cwd: Path) -> WorkerRecord:
        return await self._supervisor.start(agent_id, cwd=cwd)

    async def stop(self, agent_id: str) -> WorkerRecord | None:
        return await self._supervisor.stop(agent_id)

    async def stop_all(self) -> None:
        await self._supervisor.stop_all()
