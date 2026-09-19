"""In-memory ManagedAgentKeyStore for unit tests."""

from __future__ import annotations

from band_wezterm.auth.credentials import ManagedAgentCredentials, ManagedAgentKeyStore


class MemoryAgentKeyStore(ManagedAgentKeyStore):
    def __init__(self) -> None:
        self._records: dict[str, ManagedAgentCredentials] = {}
        self.fail_on_set = False

    def get_credentials(self, agent_id: str) -> ManagedAgentCredentials | None:
        return self._records.get(agent_id)

    def get(self, agent_id: str) -> str | None:
        record = self._records.get(agent_id)
        return None if record is None else record.api_key

    def set(self, agent_id: str, api_key: str) -> None:
        if self.fail_on_set:
            raise RuntimeError("keyring unavailable")
        self._records[agent_id] = ManagedAgentCredentials(api_key=api_key)

    def delete(self, agent_id: str) -> None:
        self._records.pop(agent_id, None)
