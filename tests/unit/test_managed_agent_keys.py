"""Managed agent API key store — INT-1484 managed namespace."""

from __future__ import annotations

from band_wezterm.auth.credentials import ManagedAgentKeyStore
from band_wezterm.config import KEYRING_MANAGED_AGENT_KEY_PREFIX


class _MemoryAgentKeys(ManagedAgentKeyStore):
    def __init__(self) -> None:
        self._keys: dict[str, str] = {}

    def get(self, agent_id: str) -> str | None:
        return self._keys.get(agent_id)

    def set(self, agent_id: str, api_key: str) -> None:
        self._keys[agent_id] = api_key

    def delete(self, agent_id: str) -> None:
        self._keys.pop(agent_id, None)


def test_managed_key_round_trip() -> None:
    store = _MemoryAgentKeys()
    store.set("agent-1", "band_a_secret")
    assert store.get("agent-1") == "band_a_secret"
    store.delete("agent-1")
    assert store.get("agent-1") is None


def test_username_prefix_matches_extension_namespace() -> None:
    store = ManagedAgentKeyStore()
    assert store._username("uuid-1") == f"{KEYRING_MANAGED_AGENT_KEY_PREFIX}uuid-1"
