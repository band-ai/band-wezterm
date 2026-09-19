"""create_agent persists the one-time managed key; keyring failure rolls back."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from band_wezterm.client import BandClient
from band_wezterm.config import Settings
from tests.memory_agent_keys import MemoryAgentKeyStore


def _register_response(*, agent_id: str, name: str, api_key: str) -> SimpleNamespace:
    return SimpleNamespace(
        data=SimpleNamespace(
            agent=SimpleNamespace(id=agent_id, name=name, harness=None),
            credentials=SimpleNamespace(api_key=api_key),
        )
    )


@pytest.mark.asyncio
async def test_create_agent_persists_managed_api_key() -> None:
    keys = MemoryAgentKeyStore()
    client = BandClient.from_user_api_key("user-key", Settings(), agent_keys=keys)
    client._agents = MagicMock()
    client._agents.register_my_agent = AsyncMock(
        return_value=_register_response(
            agent_id="a1", name="Alpha", api_key="band_a_once"
        )
    )

    record = await client.create_agent(name="Alpha", description="test")

    assert record.id == "a1"
    assert record.harness is None
    assert keys.get("a1") == "band_a_once"
    assert client.managed_agent_api_key("a1") == "band_a_once"


@pytest.mark.asyncio
async def test_create_agent_rolls_back_when_keyring_fails() -> None:
    keys = MemoryAgentKeyStore()
    keys.fail_on_set = True
    client = BandClient.from_user_api_key("user-key", Settings(), agent_keys=keys)
    client._agents = MagicMock()
    client._agents.register_my_agent = AsyncMock(
        return_value=_register_response(
            agent_id="a2", name="Beta", api_key="band_a_lost"
        )
    )
    client._agents.delete_my_agent = AsyncMock()

    with pytest.raises(RuntimeError, match="keyring unavailable"):
        await client.create_agent(name="Beta", description="test")

    client._agents.delete_my_agent.assert_awaited_once_with("a2", force=True)
    assert keys.get("a2") is None


@pytest.mark.asyncio
async def test_list_my_agents_leaves_runtime_to_the_local_profile() -> None:
    keys = MemoryAgentKeyStore()
    keys.set("a3", "band_a_key")
    client = BandClient.from_user_api_key("user-key", Settings(), agent_keys=keys)
    client._agents = MagicMock()
    client._agents.list_my_agents = AsyncMock(
        return_value=SimpleNamespace(
            data=[SimpleNamespace(id="a3", name="Gamma", harness=None, runtime=None)]
        )
    )

    agents = await client.list_my_agents()
    assert agents[0].harness is None
