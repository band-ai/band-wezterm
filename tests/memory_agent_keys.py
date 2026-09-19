"""In-memory ManagedAgentKeyStore for unit tests."""

from __future__ import annotations

from band_wezterm.auth.credentials import ManagedAgentKeyStore


class MemoryAgentKeyStore(ManagedAgentKeyStore):
    def __init__(self) -> None:
        self._keys: dict[str, str] = {}
        self.fail_on_set = False

    def get(self, agent_id: str) -> str | None:
        return self._keys.get(agent_id)

    def set(self, agent_id: str, api_key: str) -> None:
        if self.fail_on_set:
            raise RuntimeError("keyring unavailable")
        self._keys[agent_id] = api_key

    def delete(self, agent_id: str) -> None:
        self._keys.pop(agent_id, None)
