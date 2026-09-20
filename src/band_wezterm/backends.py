"""Harness metadata, persisted tuning, and catalog fallbacks."""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from pydantic import BaseModel, ConfigDict

from band_wezterm.identity import HarnessId

TUNING_DEFAULT_OPTION_ID: Final = ""
CODEX_DEFAULT_MODEL: Final = "gpt-5.6-sol"
_LEGACY_CODEX_MODELS: Final = {"gpt-5.6": CODEX_DEFAULT_MODEL}
_LEGACY_CLAUDE_EFFORTS: Final = {"off": "low", "on": "high"}


class TuningDimensionId(StrEnum):
    MODEL = "model"
    REASONING = "reasoning"


class TuningOption(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    label: str
    description: str | None = None


class TuningDimension(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: TuningDimensionId
    label: str
    options: tuple[TuningOption, ...]
    allow_custom: bool = False


class AgentTuning(BaseModel):
    """Selected values keyed by dimension — empty means adapter defaults."""

    model_config = ConfigDict(frozen=True)

    model: str = TUNING_DEFAULT_OPTION_ID
    reasoning: str = TUNING_DEFAULT_OPTION_ID

    def value_for(self, dimension: TuningDimensionId) -> str | None:
        raw = self.model if dimension is TuningDimensionId.MODEL else self.reasoning
        trimmed = raw.strip()
        if not trimmed or trimmed == TUNING_DEFAULT_OPTION_ID:
            return None
        return trimmed

    def with_dimension(self, dimension: TuningDimensionId, value: str) -> AgentTuning:
        match dimension:
            case TuningDimensionId.MODEL:
                return self.model_copy(update={"model": value})
            case TuningDimensionId.REASONING:
                return self.model_copy(update={"reasoning": value})


def normalize_tuning(harness: HarnessId, tuning: AgentTuning) -> AgentTuning:
    """Upgrade known legacy values before they reach a runtime."""
    match harness:
        case HarnessId.CODEX:
            dimension = TuningDimensionId.MODEL
            replacements = _LEGACY_CODEX_MODELS
        case HarnessId.CLAUDE | HarnessId.CLAUDE_SDK:
            dimension = TuningDimensionId.REASONING
            replacements = _LEGACY_CLAUDE_EFFORTS
        case _:
            return tuning
    replacement = replacements.get(tuning.value_for(dimension) or "")
    return (
        tuning
        if replacement is None
        else tuning.with_dimension(dimension, replacement)
    )


class HarnessBackend(BaseModel):
    model_config = ConfigDict(frozen=True)

    harness: HarnessId
    label: str
    badge: str
    tuning: tuple[TuningDimension, ...] = ()


_DEFAULT = TuningOption(id=TUNING_DEFAULT_OPTION_ID, label="Adapter default")


_CLAUDE_MODEL_FALLBACKS: Final = (
    _DEFAULT,
    TuningOption(id="fable", label="Fable"),
    TuningOption(id="opus", label="Opus"),
    TuningOption(id="sonnet", label="Sonnet"),
    TuningOption(id="haiku", label="Haiku"),
    TuningOption(
        id="opusplan",
        label="Opus, then Sonnet",
        description="Opus while planning, Sonnet to execute",
    ),
)

_CATALOG_FALLBACK: Final = (_DEFAULT,)

HARNESS_BACKENDS: Final[tuple[HarnessBackend, ...]] = (
    HarnessBackend(
        harness=HarnessId.CLAUDE_SDK,
        label="Claude",
        badge="CL",
        tuning=(
            TuningDimension(
                id=TuningDimensionId.MODEL,
                label="Model",
                options=_CLAUDE_MODEL_FALLBACKS,
                allow_custom=True,
            ),
            TuningDimension(
                id=TuningDimensionId.REASONING,
                label="Effort",
                options=_CATALOG_FALLBACK,
                allow_custom=True,
            ),
        ),
    ),
    HarnessBackend(
        harness=HarnessId.CODEX,
        label="Codex",
        badge="CX",
        tuning=(
            TuningDimension(
                id=TuningDimensionId.MODEL,
                label="Model",
                options=_CATALOG_FALLBACK,
                allow_custom=True,
            ),
            TuningDimension(
                id=TuningDimensionId.REASONING,
                label="Reasoning effort",
                options=_CATALOG_FALLBACK,
                allow_custom=True,
            ),
        ),
    ),
    HarnessBackend(
        harness=HarnessId.COPILOT_SDK,
        label="Copilot",
        badge="CP",
        tuning=(
            TuningDimension(
                id=TuningDimensionId.MODEL,
                label="Model",
                options=_CATALOG_FALLBACK,
                allow_custom=True,
            ),
            TuningDimension(
                id=TuningDimensionId.REASONING,
                label="Reasoning effort",
                options=_CATALOG_FALLBACK,
                allow_custom=True,
            ),
        ),
    ),
    HarnessBackend(
        harness=HarnessId.OPENCODE,
        label="OpenCode",
        badge="OM",
        tuning=(
            TuningDimension(
                id=TuningDimensionId.MODEL,
                label="Model id",
                options=(_DEFAULT,),
                allow_custom=True,
            ),
            TuningDimension(
                id=TuningDimensionId.REASONING,
                label="Variant / effort",
                options=_CATALOG_FALLBACK,
                allow_custom=True,
            ),
        ),
    ),
)

DEFAULT_HARNESS: Final = HarnessId.CLAUDE_SDK

_BACKENDS_BY_HARNESS: Final = {backend.harness: backend for backend in HARNESS_BACKENDS}


def list_backends() -> tuple[HarnessBackend, ...]:
    return HARNESS_BACKENDS


def resolve_backend(harness: HarnessId | str) -> HarnessBackend:
    key = HarnessId(harness)
    # Accept aliases that share a badge/runtime.
    aliases: dict[HarnessId, HarnessId] = {
        HarnessId.CLAUDE: HarnessId.CLAUDE_SDK,
        HarnessId.COPILOT: HarnessId.COPILOT_SDK,
        HarnessId.OMP: HarnessId.OPENCODE,
    }
    resolved = aliases.get(key, key)
    try:
        return _BACKENDS_BY_HARNESS[resolved]
    except KeyError as error:
        raise ValueError(f"Unknown harness backend {harness!r}") from error


def describe_tuning_value(harness: HarnessId, tuning: AgentTuning, dimension: TuningDimensionId) -> str:
    backend = resolve_backend(harness)
    dim = next((item for item in backend.tuning if item.id is dimension), None)
    chosen = tuning.value_for(dimension) or TUNING_DEFAULT_OPTION_ID
    if dim is None:
        return chosen or "default"
    option = next((item for item in dim.options if item.id == chosen), None)
    return option.label if option is not None else chosen or "default"
