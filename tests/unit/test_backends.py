"""Harness backends and tuning helpers."""

from __future__ import annotations

from band_wezterm.backends import (
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
