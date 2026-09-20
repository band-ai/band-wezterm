"""Lazy, cached live catalog loading."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Final

from band_wezterm.agent.opencode_server import OpenCodeServerManager
from band_wezterm.catalogs.models import HarnessCatalog
from band_wezterm.catalogs.providers import (
    load_claude_catalog,
    load_codex_catalog,
    load_copilot_catalog,
    load_opencode_catalog,
)
from band_wezterm.identity import HarnessId

CatalogLoader = Callable[[], Awaitable[HarnessCatalog]]

_CATALOG_ALIASES: Final = {
    HarnessId.CLAUDE: HarnessId.CLAUDE_SDK,
    HarnessId.COPILOT: HarnessId.COPILOT_SDK,
    HarnessId.OMP: HarnessId.OPENCODE,
}


class ModelCatalogService:
    """Load each local runtime catalog once per Control lifetime."""

    def __init__(
        self,
        opencode_server: OpenCodeServerManager,
        *,
        loaders: dict[HarnessId, CatalogLoader] | None = None,
    ) -> None:
        self._loaders = loaders or {
            HarnessId.CLAUDE_SDK: load_claude_catalog,
            HarnessId.CODEX: load_codex_catalog,
            HarnessId.COPILOT_SDK: load_copilot_catalog,
            HarnessId.OPENCODE: lambda: load_opencode_catalog(opencode_server),
        }
        self._catalogs: dict[HarnessId, HarnessCatalog] = {}
        self._locks: dict[HarnessId, asyncio.Lock] = {}

    async def load(self, harness: HarnessId) -> HarnessCatalog:
        key = _CATALOG_ALIASES.get(harness, harness)
        if cached := self._catalogs.get(key):
            return cached
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if cached := self._catalogs.get(key):
                return cached
            catalog = await self._loaders[key]()
            self._catalogs[key] = catalog
            return catalog

    def get(self, harness: HarnessId) -> HarnessCatalog | None:
        key = _CATALOG_ALIASES.get(harness, harness)
        return self._catalogs.get(key)
