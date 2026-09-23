"""The stable extension contract for a supported agent harness."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

from band_wezterm.agent.opencode_server import OpenCodeServerManager
from band_wezterm.catalogs.models import HarnessCatalog
from band_wezterm.harnesses.models import AgentTuning, HarnessBackend
from band_wezterm.identity import HarnessId


class HarnessUnavailableError(RuntimeError):
    """A selected harness cannot be used in the current installation."""


@dataclass(frozen=True)
class AdapterRequest:
    """Runtime-only inputs shared by every provider adapter factory."""

    cwd: Path | None = None
    persona: str | None = None
    tuning: AgentTuning = field(default_factory=AgentTuning)
    opencode_server_url: str | None = None


class HarnessProvider(ABC):
    """One implementation owns one canonical harness and its aliases."""

    backend: HarnessBackend
    aliases: tuple[HarnessId, ...] = ()

    @property
    def id(self) -> HarnessId:
        return self.backend.harness

    @property
    def identifiers(self) -> tuple[HarnessId, ...]:
        return (self.id, *self.aliases)

    @abstractmethod
    def build_adapter(self, request: AdapterRequest) -> object:
        """Build the installed band-sdk adapter for one managed worker."""

    @abstractmethod
    async def load_catalog(self, server: OpenCodeServerManager) -> HarnessCatalog:
        """Load the live model catalog for the registration screen."""
