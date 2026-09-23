"""Provider-neutral harness metadata and persisted tuning."""

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
    """Selected values keyed by dimension; empty selects adapter defaults."""

    model_config = ConfigDict(frozen=True)

    model: str = TUNING_DEFAULT_OPTION_ID
    reasoning: str = TUNING_DEFAULT_OPTION_ID

    def value_for(self, dimension: TuningDimensionId) -> str | None:
        raw = self.model if dimension is TuningDimensionId.MODEL else self.reasoning
        return raw.strip() or None

    def with_dimension(self, dimension: TuningDimensionId, value: str) -> AgentTuning:
        match dimension:
            case TuningDimensionId.MODEL:
                return self.model_copy(update={"model": value})
            case TuningDimensionId.REASONING:
                return self.model_copy(update={"reasoning": value})


class HarnessBackend(BaseModel):
    """Static UI metadata supplied by one registered harness provider."""

    model_config = ConfigDict(frozen=True)

    harness: HarnessId
    label: str
    badge: str
    tuning: tuple[TuningDimension, ...] = ()


def normalize_tuning(harness: HarnessId, tuning: AgentTuning) -> AgentTuning:
    """Upgrade persisted legacy values before passing them to a provider."""
    match harness:
        case HarnessId.CODEX:
            dimension, replacements = TuningDimensionId.MODEL, _LEGACY_CODEX_MODELS
        case HarnessId.CLAUDE | HarnessId.CLAUDE_SDK:
            dimension, replacements = TuningDimensionId.REASONING, _LEGACY_CLAUDE_EFFORTS
        case _:
            return tuning
    replacement = replacements.get(tuning.value_for(dimension) or "")
    return tuning if replacement is None else tuning.with_dimension(dimension, replacement)
