"""Harness backends and tuning helpers."""

from __future__ import annotations

from band_wezterm.backends import (
    TUNING_DEFAULT_OPTION_ID,
    AgentTuning,
    TuningDimensionId,
    describe_tuning_value,
    list_backends,
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


def test_copilot_exposes_reasoning_effort() -> None:
    backend = resolve_backend(HarnessId.COPILOT_SDK)
    reasoning = next(
        dimension
        for dimension in backend.tuning
        if dimension.id is TuningDimensionId.REASONING
    )
    assert [option.id for option in reasoning.options] == [
        TUNING_DEFAULT_OPTION_ID,
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
    ]


def test_codex_exposes_models_reported_by_the_current_runtime() -> None:
    backend = resolve_backend(HarnessId.CODEX)
    model = next(
        dimension
        for dimension in backend.tuning
        if dimension.id is TuningDimensionId.MODEL
    )

    assert [option.id for option in model.options] == [
        TUNING_DEFAULT_OPTION_ID,
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-6-astra",
        "gpt-5.5",
    ]


def test_copilot_exposes_models_reported_by_the_current_runtime() -> None:
    backend = resolve_backend(HarnessId.COPILOT_SDK)
    model = next(
        dimension
        for dimension in backend.tuning
        if dimension.id is TuningDimensionId.MODEL
    )

    assert [option.id for option in model.options] == [
        TUNING_DEFAULT_OPTION_ID,
        "claude-sonnet-5",
        "claude-haiku-4.5",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.3-codex",
        "gpt-5-mini",
        "mai-code-1.1-flash",
        "grok-4.5",
        "kimi-k3",
        "kimi-k2.7-code",
        "grok-4.6",
    ]
