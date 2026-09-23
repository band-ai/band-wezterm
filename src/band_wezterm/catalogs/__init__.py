"""Live harness model and effort catalogs."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING

from band_wezterm.catalogs.models import HarnessCatalog, ModelCatalogEntry

if TYPE_CHECKING:
    from band_wezterm.catalogs.service import ModelCatalogService


def __getattr__(name: str) -> object:
    if name == "ModelCatalogService":
        module = import_module("band_wezterm.catalogs.service")
        return module.ModelCatalogService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["HarnessCatalog", "ModelCatalogEntry", "ModelCatalogService"]
