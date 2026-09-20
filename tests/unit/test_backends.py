"""Harness backends and tuning helpers."""

from __future__ import annotations

from band_wezterm.backends import (
    TUNING_DEFAULT_OPTION_ID,
    AgentTuning,
    TuningDimensionId,
    describe_tuning_value,
    list_backends,
    normalize_tuning,
    resolve_backend,
)
from band_wezterm.identity import HarnessId


def test_list_backends_covers_four_runtimes() -> None:
    harnesses = {backend.harness for backend in list_backends()}
    assert HarnessId.CLAUDE_SDK in harnesses
    assert HarnessId.CODEX in harnesses
    assert HarnessId.COPILOT_SDK in harnesses
    assert HarnessId.OPENCODE in harnesses


def test_resolve_backend_aliases() -> None:
    assert resolve_backend(HarnessId.CLAUDE).harness is HarnessId.CLAUDE_SDK
    assert resolve_backend(HarnessId.OMP).harness is HarnessId.OPENCODE


def test_tuning_value_for_and_describe() -> None:
    tuning = AgentTuning(model="sonnet", reasoning="off")
    assert tuning.value_for(TuningDimensionId.MODEL) == "sonnet"
    assert tuning.value_for(TuningDimensionId.REASONING) == "off"
    assert (
        describe_tuning_value(HarnessId.CLAUDE_SDK, tuning, TuningDimensionId.MODEL)
        == "Sonnet"
    )
    assert AgentTuning().value_for(TuningDimensionId.MODEL) is None


def test_copilot_reasoning_uses_live_catalog_fallback() -> None:
    backend = resolve_backend(HarnessId.COPILOT_SDK)
    reasoning = next(
        dimension
        for dimension in backend.tuning
        if dimension.id is TuningDimensionId.REASONING
    )
    assert [option.id for option in reasoning.options] == [TUNING_DEFAULT_OPTION_ID]


def test_claude_effort_uses_live_catalog_fallback() -> None:
    backend = resolve_backend(HarnessId.CLAUDE_SDK)
    reasoning = next(
        dimension
        for dimension in backend.tuning
        if dimension.id is TuningDimensionId.REASONING
    )
    assert reasoning.label == "Effort"
    assert [option.id for option in reasoning.options] == [TUNING_DEFAULT_OPTION_ID]


def test_legacy_claude_thinking_values_migrate_to_effort() -> None:
    assert normalize_tuning(
        HarnessId.CLAUDE_SDK, AgentTuning(reasoning="off")
    ).reasoning == "low"
    assert normalize_tuning(
        HarnessId.CLAUDE, AgentTuning(reasoning="on")
    ).reasoning == "high"


def test_codex_models_use_live_catalog_fallback() -> None:
    backend = resolve_backend(HarnessId.CODEX)
    model = next(
        dimension
        for dimension in backend.tuning
        if dimension.id is TuningDimensionId.MODEL
    )

    assert [option.id for option in model.options] == [TUNING_DEFAULT_OPTION_ID]


def test_copilot_models_use_live_catalog_fallback() -> None:
    backend = resolve_backend(HarnessId.COPILOT_SDK)
    model = next(
        dimension
        for dimension in backend.tuning
        if dimension.id is TuningDimensionId.MODEL
    )

    assert [option.id for option in model.options] == [TUNING_DEFAULT_OPTION_ID]
