"""Harness-specific live catalog discovery."""

from __future__ import annotations

import importlib
from collections.abc import Iterable
from typing import Any, Final, get_args

import httpx
from pydantic import BaseModel, ConfigDict, Field

from band_wezterm.agent.opencode_server import OpenCodeServerManager
from band_wezterm.backends import TuningOption
from band_wezterm.catalogs.models import HarnessCatalog, ModelCatalogEntry

_CATALOG_CLIENT_NAME: Final = "band-wezterm"
_CATALOG_CLIENT_TITLE: Final = "Band WezTerm"
_CATALOG_CLIENT_VERSION: Final = "0"
_OPENCODE_PROVIDERS_PATH: Final = "/config/providers"


class _CodexEffort(BaseModel):
    model_config = ConfigDict(extra="ignore")

    reasoning_effort: str = Field(alias="reasoningEffort")
    description: str | None = None


class _CodexModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    display_name: str = Field(alias="displayName")
    description: str | None = None
    hidden: bool = False
    efforts: tuple[_CodexEffort, ...] = Field(alias="supportedReasoningEfforts")
    is_default: bool = Field(False, alias="isDefault")


class _CodexCatalog(BaseModel):
    model_config = ConfigDict(extra="ignore")

    data: tuple[_CodexModel, ...]


class _OpenCodeModel(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str
    provider_id: str = Field(alias="providerID")
    name: str
    status: str = "active"
    variants: dict[str, object] = Field(default_factory=dict)


class _OpenCodeProvider(BaseModel):
    model_config = ConfigDict(extra="ignore")

    models: dict[str, _OpenCodeModel]


class _OpenCodeCatalog(BaseModel):
    model_config = ConfigDict(extra="ignore")

    providers: tuple[_OpenCodeProvider, ...]
    defaults: dict[str, str] = Field(default_factory=dict, alias="default")


async def load_claude_catalog() -> HarnessCatalog:
    """Read the installed Claude SDK contract; it has no model-list API."""
    sdk = importlib.import_module("claude_agent_sdk")
    options = sdk.ClaudeAgentOptions
    effort_type = options.__annotations__["effort"]
    efforts = tuple(_option(value) for value in _literal_values(effort_type))
    return HarnessCatalog(
        models=(
            ModelCatalogEntry(id="fable", label="Fable", efforts=efforts),
            ModelCatalogEntry(id="opus", label="Opus", efforts=efforts),
            ModelCatalogEntry(id="sonnet", label="Sonnet", efforts=efforts),
            ModelCatalogEntry(id="haiku", label="Haiku", efforts=efforts),
            ModelCatalogEntry(
                id="opusplan",
                label="Opus, then Sonnet",
                description="Opus while planning, Sonnet to execute",
                efforts=efforts,
            ),
        ),
    )


async def load_codex_catalog() -> HarnessCatalog:
    integration = importlib.import_module("band.integrations.codex")
    client = integration.CodexStdioClient()
    try:
        await client.connect()
        await client.initialize(
            client_name=_CATALOG_CLIENT_NAME,
            client_title=_CATALOG_CLIENT_TITLE,
            client_version=_CATALOG_CLIENT_VERSION,
            experimental_api=True,
        )
        payload = await client.request("model/list", {})
    finally:
        await client.close()
    return codex_catalog_from_payload(payload)


def codex_catalog_from_payload(payload: object) -> HarnessCatalog:
    parsed = _CodexCatalog.model_validate(payload)
    visible = tuple(model for model in parsed.data if not model.hidden)
    return HarnessCatalog(
        models=tuple(
            ModelCatalogEntry(
                id=model.id,
                label=model.display_name,
                description=model.description,
                efforts=tuple(
                    TuningOption(
                        id=effort.reasoning_effort,
                        label=effort.reasoning_effort.capitalize(),
                        description=effort.description,
                    )
                    for effort in model.efforts
                ),
            )
            for model in visible
        ),
        default_model_id=next(
            (model.id for model in visible if model.is_default),
            None,
        ),
    )


async def load_copilot_catalog() -> HarnessCatalog:
    copilot = importlib.import_module("copilot")
    client = copilot.CopilotClient(log_level="error")
    try:
        await client.start()
        discovered = await client.list_models()
    finally:
        await client.stop()
    return copilot_catalog_from_models(discovered)


def copilot_catalog_from_models(discovered: Iterable[Any]) -> HarnessCatalog:
    return HarnessCatalog(
        models=tuple(
            ModelCatalogEntry(
                id=model.id,
                label=model.name,
                efforts=tuple(
                    _option(effort)
                    for effort in (model.supported_reasoning_efforts or ())
                ),
            )
            for model in discovered
            if model.id != "auto"
        )
    )


async def load_opencode_catalog(
    server: OpenCodeServerManager,
) -> HarnessCatalog:
    endpoint = await server.ensure()
    async with httpx.AsyncClient() as client:
        response = await client.get(f"{endpoint.url}{_OPENCODE_PROVIDERS_PATH}")
        response.raise_for_status()
    return opencode_catalog_from_payload(response.json())


def opencode_catalog_from_payload(payload: object) -> HarnessCatalog:
    parsed = _OpenCodeCatalog.model_validate(payload)
    models = tuple(
        _opencode_entry(model)
        for provider in parsed.providers
        for model in provider.models.values()
        if model.status == "active"
    )
    default_model_id = next(
        (
            _full_opencode_model_id(model)
            for provider in parsed.providers
            for model in provider.models.values()
            if parsed.defaults.get(model.provider_id) == model.id
        ),
        None,
    )
    return HarnessCatalog(models=models, default_model_id=default_model_id)


def _opencode_entry(model: _OpenCodeModel) -> ModelCatalogEntry:
    return ModelCatalogEntry(
        id=_full_opencode_model_id(model),
        label=f"{model.name} ({model.provider_id})",
        efforts=tuple(_option(variant) for variant in model.variants),
    )


def _full_opencode_model_id(model: _OpenCodeModel) -> str:
    return f"{model.provider_id}/{model.id}"


def _option(value: str) -> TuningOption:
    return TuningOption(id=value, label=value.capitalize())


def _literal_values(annotation: Any) -> Iterable[str]:
    for candidate in get_args(annotation):
        values = get_args(candidate)
        if values and all(isinstance(value, str) for value in values):
            yield from values
