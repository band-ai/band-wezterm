"""Lazy, cached live catalog loading."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from band_wezterm.agent.opencode_server import OpenCodeServerManager
from band_wezterm.catalogs.models import HarnessCatalog
from band_wezterm.harnesses.registry import DEFAULT_REGISTRY
from band_wezterm.identity import HarnessId

CatalogLoader = Callable[[], Awaitable[HarnessCatalog]]

class ModelCatalogService:
    """Load each local runtime catalog once per Control lifetime."""

    def __init__(
        self,
        opencode_server: OpenCodeServerManager,
        *,
        loaders: dict[HarnessId, CatalogLoader] | None = None,
    ) -> None:
        self._loaders = loaders or {
            provider.id: (lambda provider=provider: provider.load_catalog(opencode_server))
            for provider in DEFAULT_REGISTRY.list()
        }
        self._catalogs: dict[HarnessId, HarnessCatalog] = {}
        self._locks: dict[HarnessId, asyncio.Lock] = {}

    async def load(self, harness: HarnessId) -> HarnessCatalog:
        key = DEFAULT_REGISTRY.resolve(harness).id
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
        key = DEFAULT_REGISTRY.resolve(harness).id
        return self._catalogs.get(key)
