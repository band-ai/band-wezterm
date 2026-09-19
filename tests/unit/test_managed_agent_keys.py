"""Managed agent API key store — INT-1484 managed namespace."""

from __future__ import annotations

from band_wezterm.auth.credentials import ManagedAgentKeyStore
from band_wezterm.config import KEYRING_MANAGED_AGENT_KEY_PREFIX
from tests.memory_agent_keys import MemoryAgentKeyStore


def test_managed_key_round_trip() -> None:
    from band_wezterm.identity import HarnessId

    store = MemoryAgentKeyStore()
    store.set("agent-1", "band_a_secret", harness=HarnessId.CODEX)
    assert store.get("agent-1") == "band_a_secret"
    assert store.get_harness("agent-1") is HarnessId.CODEX
    store.delete("agent-1")
    assert store.get("agent-1") is None


def test_username_prefix_matches_extension_namespace() -> None:
    store = ManagedAgentKeyStore()
    assert store._username("uuid-1") == f"{KEYRING_MANAGED_AGENT_KEY_PREFIX}uuid-1"
