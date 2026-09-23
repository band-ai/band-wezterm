"""Compatibility exports for harness metadata.

New harnesses belong in :mod:`band_wezterm.harnesses.providers`; this module
preserves the original import path for persisted-profile consumers.
"""

from band_wezterm.harnesses.models import (
    CODEX_DEFAULT_MODEL,
    TUNING_DEFAULT_OPTION_ID,
    AgentTuning,
    HarnessBackend,
    TuningDimension,
    TuningDimensionId,
    TuningOption,
    normalize_tuning,
)
from band_wezterm.harnesses.registry import (
    DEFAULT_HARNESS,
    describe_tuning_value,
    list_backends,
    resolve_backend,
)

__all__ = [
    "CODEX_DEFAULT_MODEL",
    "DEFAULT_HARNESS",
    "TUNING_DEFAULT_OPTION_ID",
    "AgentTuning",
    "HarnessBackend",
    "TuningDimension",
    "TuningDimensionId",
    "TuningOption",
    "describe_tuning_value",
    "list_backends",
    "normalize_tuning",
    "resolve_backend",
]
