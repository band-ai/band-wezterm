"""Room and agent mutations shared by the CLI and TUI."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest

from band_wezterm.client import BandClient
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.resource_operations import ManagedAgentOperations
from band_wezterm.supervisor import ManagedAgentLifecycle


@pytest.mark.asyncio
async def test_deleting_a_managed_agent_removes_its_durable_profile() -> None:
    client = create_autospec(BandClient, spec_set=True, instance=True)
    lifecycle = create_autospec(ManagedAgentLifecycle, spec_set=True, instance=True)
    profiles = create_autospec(ManagedAgentStore, spec_set=True, instance=True)
    worker = MagicMock()
    lifecycle.stop = AsyncMock(return_value=worker)
    client.delete_agent = AsyncMock()
    operations = ManagedAgentOperations(client, lifecycle, profiles)

    assert await operations.delete("agent-1") is worker

    lifecycle.stop.assert_awaited_once_with("agent-1")
    client.delete_agent.assert_awaited_once_with("agent-1")
    profiles.remove.assert_called_once_with("agent-1")
