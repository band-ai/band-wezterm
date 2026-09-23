"""Detached worker lifecycle delegates only through the supervisor boundary."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, create_autospec

import pytest

from band_wezterm.supervisor import ManagedAgentLifecycle, SupervisorClient


@pytest.mark.asyncio
async def test_lifecycle_delegates_runtime_operations() -> None:
    supervisor = create_autospec(SupervisorClient, spec_set=True, instance=True)
    supervisor.list_workers = AsyncMock(return_value=())
    supervisor.start = AsyncMock()
    supervisor.stop = AsyncMock()
    supervisor.stop_all = AsyncMock()
    lifecycle = ManagedAgentLifecycle(supervisor)

    assert await lifecycle.workers() == ()
    await lifecycle.start("agent-1", cwd=Path.cwd())
    await lifecycle.stop("agent-1")
    await lifecycle.stop_all()

    supervisor.list_workers.assert_awaited_once()
    supervisor.start.assert_awaited_once_with("agent-1", cwd=Path.cwd())
    supervisor.stop.assert_awaited_once_with("agent-1")
    supervisor.stop_all.assert_awaited_once()
