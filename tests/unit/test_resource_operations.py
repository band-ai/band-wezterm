"""Room and agent mutations shared by the CLI and TUI."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, create_autospec

import pytest

from band_wezterm.client import BandClient, RoomRecord
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.resource_operations import ManagedAgentOperations, RoomOperations
from band_wezterm.supervisor import ManagedAgentLifecycle


@pytest.mark.asyncio
async def test_room_operations_delegate_catalog_mutations() -> None:
    client = create_autospec(BandClient, spec_set=True, instance=True)
    room = RoomRecord(id="room-1", title="Planning", color="#000000")
    client.create_room = AsyncMock(return_value=room)
    client.delete_room = AsyncMock()
    operations = RoomOperations(client)

    assert await operations.create("Planning") == room
    await operations.delete(room.id)

    client.create_room.assert_awaited_once_with(title=room.title)
    client.delete_room.assert_awaited_once_with(room.id)


@pytest.mark.asyncio
async def test_managed_agent_operations_own_runtime_and_profile_cleanup() -> None:
    client = create_autospec(BandClient, spec_set=True, instance=True)
    lifecycle = create_autospec(ManagedAgentLifecycle, spec_set=True, instance=True)
    profiles = create_autospec(ManagedAgentStore, spec_set=True, instance=True)
    worker = MagicMock()
    lifecycle.start = AsyncMock(return_value=worker)
    lifecycle.stop = AsyncMock(return_value=worker)
    lifecycle.stop_all = AsyncMock()
    client.delete_agent = AsyncMock()
    operations = ManagedAgentOperations(client, lifecycle, profiles)

    assert await operations.start("agent-1", cwd=Path.cwd()) is worker
    assert await operations.stop("agent-1") is worker
    await operations.stop_all()
    assert await operations.delete("agent-1") is worker

    lifecycle.start.assert_awaited_once_with("agent-1", cwd=Path.cwd())
    lifecycle.stop.assert_awaited_with("agent-1")
    lifecycle.stop_all.assert_awaited_once()
    client.delete_agent.assert_awaited_once_with("agent-1")
    profiles.remove.assert_called_once_with("agent-1")
