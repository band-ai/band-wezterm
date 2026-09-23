"""Room and agent mutations shared by the CLI and TUI."""

from __future__ import annotations

from unittest.mock import AsyncMock, create_autospec

import pytest

from band_wezterm.client import BandClient
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.resource_operations import ManagedAgentOperations, ResourceEvent
from band_wezterm.supervisor import ManagedAgentLifecycle, WorkerRecord, WorkerState


@pytest.mark.asyncio
async def test_deleting_a_managed_agent_records_safe_lifecycle_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = create_autospec(BandClient, spec_set=True, instance=True)
    lifecycle = create_autospec(ManagedAgentLifecycle, spec_set=True, instance=True)
    profiles = create_autospec(ManagedAgentStore, spec_set=True, instance=True)
    worker = WorkerRecord(
        agent_id="agent-1",
        name="Architect",
        pid=1,
        control_socket="/tmp/band-worker.sock",
        control_token="worker-token",
        cwd="/workspace",
        started_at=0,
        state=WorkerState.STOPPING,
    )
    lifecycle.stop = AsyncMock(return_value=worker)
    client.delete_agent = AsyncMock()
    operations = ManagedAgentOperations(client, lifecycle, profiles)
    events: list[tuple[ResourceEvent, dict[str, object]]] = []
    monkeypatch.setattr(
        "band_wezterm.resource_operations.log_event",
        lambda event, **context: events.append((ResourceEvent(event), context)),
    )

    assert await operations.delete("agent-1") is worker

    lifecycle.stop.assert_awaited_once_with("agent-1")
    client.delete_agent.assert_awaited_once_with("agent-1")
    profiles.remove.assert_called_once_with("agent-1")
    assert events == [
        (ResourceEvent.AGENT_DELETE_REQUESTED, {"agent_id": "agent-1"}),
        (ResourceEvent.AGENT_STOP_REQUESTED, {"agent_id": "agent-1"}),
        (
            ResourceEvent.AGENT_STOPPED,
            {"agent_id": "agent-1", "state": WorkerState.STOPPING.value},
        ),
        (ResourceEvent.AGENT_DELETED, {"agent_id": "agent-1"}),
    ]
