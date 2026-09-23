"""Single registry for supported agent harnesses."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final

from band_wezterm.harnesses.base import (
    AdapterRequest,
    HarnessProvider,
    HarnessUnavailableError,
)
from band_wezterm.harnesses.models import (
    AgentTuning,
    HarnessBackend,
    TuningDimensionId,
    normalize_tuning,
)
from band_wezterm.harnesses.providers import BUILTIN_HARNESSES
from band_wezterm.identity import HarnessId


class HarnessRegistry:
    """Resolve each persisted alias to one canonical provider."""

    def __init__(self, providers: Iterable[HarnessProvider]) -> None:
        self._providers = tuple(providers)
        self._by_identifier = {
            identifier: provider
            for provider in self._providers
            for identifier in provider.identifiers
        }
        if len(self._by_identifier) != sum(
            len(provider.identifiers) for provider in self._providers
        ):
            raise ValueError("Harness identifiers must be unique.")

    def resolve(self, harness: HarnessId | str | None) -> HarnessProvider:
        if harness is None:
            raise HarnessUnavailableError("Agent has no harness; re-register with one.")
        try:
            key = HarnessId(harness)
        except ValueError as error:
            raise HarnessUnavailableError(f"Unknown harness {harness!r}.") from error
        try:
            return self._by_identifier[key]
        except KeyError as error:
            raise HarnessUnavailableError(f"Unsupported harness {key.value!r}.") from error

    def list(self) -> tuple[HarnessProvider, ...]:
        return self._providers

    def build_adapter(self, harness: HarnessId | str | None, request: AdapterRequest) -> object:
        provider = self.resolve(harness)
        return provider.build_adapter(
            request.__class__(
                cwd=request.cwd,
                persona=request.persona,
                tuning=normalize_tuning(provider.id, request.tuning),
                opencode_server_url=request.opencode_server_url,
            )
        )


DEFAULT_HARNESS: Final = HarnessId.CLAUDE_SDK
DEFAULT_REGISTRY: Final = HarnessRegistry(BUILTIN_HARNESSES)


def list_backends() -> tuple[HarnessBackend, ...]:
    return tuple(provider.backend for provider in DEFAULT_REGISTRY.list())


def resolve_backend(harness: HarnessId | str) -> HarnessBackend:
    return DEFAULT_REGISTRY.resolve(harness).backend


def describe_tuning_value(
    harness: HarnessId, tuning: AgentTuning, dimension: TuningDimensionId
) -> str:
    backend = resolve_backend(harness)
    selected = tuning.value_for(dimension) or ""
    configured = next((item for item in backend.tuning if item.id is dimension), None)
    if configured is None:
        return selected or "default"
    option = next((item for item in configured.options if item.id == selected), None)
    return option.label if option is not None else selected or "default"
