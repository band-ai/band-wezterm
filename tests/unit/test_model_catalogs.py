"""Live model catalog normalization and caching."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

from band_wezterm.agent.opencode_server import OpenCodeServerManager
from band_wezterm.backends import TuningDimension, TuningDimensionId, TuningOption
from band_wezterm.catalogs import HarnessCatalog, ModelCatalogEntry, ModelCatalogService
from band_wezterm.catalogs.providers import (
    codex_catalog_from_payload,
    copilot_catalog_from_models,
    opencode_catalog_from_payload,
)
from band_wezterm.identity import HarnessId


def test_codex_catalog_preserves_per_model_efforts_and_default() -> None:
    catalog = codex_catalog_from_payload(
        {
            "data": [
                {
                    "id": "visible",
                    "displayName": "Visible",
                    "description": "Current account model",
                    "supportedReasoningEfforts": [
                        {"reasoningEffort": "low", "description": "Fast"},
                        {"reasoningEffort": "max", "description": "Deep"},
                    ],
                    "isDefault": True,
                },
                {
                    "id": "hidden",
                    "displayName": "Hidden",
                    "hidden": True,
                    "supportedReasoningEfforts": [],
                },
            ]
        }
    )

    assert [model.id for model in catalog.models] == ["visible"]
    assert catalog.default_model_id == "visible"
    assert [effort.id for effort in catalog.models[0].efforts] == ["low", "max"]


def test_copilot_catalog_excludes_auto_and_keeps_model_specific_efforts() -> None:
    catalog = copilot_catalog_from_models(
        [
            SimpleNamespace(
                id="auto",
                name="Auto",
                supported_reasoning_efforts=None,
            ),
            SimpleNamespace(
                id="model-a",
                name="Model A",
                supported_reasoning_efforts=["low", "high"],
            ),
            SimpleNamespace(
                id="model-b",
                name="Model B",
                supported_reasoning_efforts=None,
            ),
        ]
    )

    assert [model.id for model in catalog.models] == ["model-a", "model-b"]
    assert [effort.id for effort in catalog.models[0].efforts] == ["low", "high"]
    assert catalog.models[1].efforts == ()


def test_opencode_catalog_uses_full_model_ids_and_variants() -> None:
    catalog = opencode_catalog_from_payload(
        {
            "providers": [
                {
                    "models": {
                        "model": {
                            "id": "family/model",
                            "providerID": "provider",
                            "name": "Model",
                            "variants": {"low": {}, "max": {}},
                        },
                        "retired": {
                            "id": "retired",
                            "providerID": "provider",
                            "name": "Retired",
                            "status": "deprecated",
                        },
                    }
                }
            ],
            "default": {"provider": "family/model"},
        }
    )

    assert [model.id for model in catalog.models] == ["provider/family/model"]
    assert catalog.default_model_id == "provider/family/model"
    assert [effort.id for effort in catalog.models[0].efforts] == ["low", "max"]


def test_catalog_reasoning_options_follow_the_selected_model() -> None:
    catalog = HarnessCatalog(
        models=(
            ModelCatalogEntry(
                id="reasoning",
                label="Reasoning",
                efforts=(TuningOption(id="high", label="High"),),
            ),
            ModelCatalogEntry(id="plain", label="Plain"),
        ),
    )
    fallback = TuningDimension(
        id=TuningDimensionId.REASONING,
        label="Effort",
        options=(TuningOption(id="", label="Adapter default"),),
    )

    reasoning = catalog.dimension(fallback, selected_model="reasoning")
    plain = catalog.dimension(fallback, selected_model="plain")

    assert [option.id for option in reasoning.options] == ["", "high"]
    assert [option.id for option in plain.options] == [""]


async def test_catalog_service_coalesces_concurrent_loads() -> None:
    calls = 0

    async def load() -> HarnessCatalog:
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return HarnessCatalog(models=())

    service = ModelCatalogService(
        MagicMock(spec=OpenCodeServerManager),
        loaders={HarnessId.CODEX: load},
    )

    first, second = await asyncio.gather(
        service.load(HarnessId.CODEX),
        service.load(HarnessId.CODEX),
    )

    assert first is second
    assert calls == 1
