"""Harness adapter factory — mapping and missing-extra errors."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from band_wezterm.agent.adapters import (
    HarnessUnavailableError,
    build_adapter,
    preflight_harness,
)
from band_wezterm.backends import AgentTuning
from band_wezterm.identity import HarnessId


@pytest.mark.parametrize(
    ("harness", "attr"),
    [
        (HarnessId.CLAUDE_SDK, "_claude"),
        (HarnessId.CLAUDE, "_claude"),
        (HarnessId.CODEX, "_codex"),
        (HarnessId.COPILOT_SDK, "_copilot"),
        (HarnessId.COPILOT, "_copilot"),
        (HarnessId.OPENCODE, "_opencode"),
        (HarnessId.OMP, "_opencode"),
    ],
)
def test_build_adapter_routes_harness(
    harness: HarnessId, attr: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    sentinel = MagicMock(name=attr)
    monkeypatch.setattr(
        f"band_wezterm.agent.adapters.{attr}",
        lambda *args, **kwargs: sentinel,
    )
    assert build_adapter(harness, cwd=Path("/tmp/work")) is sentinel


def test_build_adapter_rejects_missing_harness() -> None:
    with pytest.raises(HarnessUnavailableError, match="no harness"):
        build_adapter(None)


def test_preflight_surfaces_import_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_args: object, **_kwargs: object) -> None:
        raise HarnessUnavailableError(
            "Harness claude_sdk requires `uv sync --extra claude_sdk` "
            "(or `--extra agents`; installs band-sdk[claude-sdk]). "
            "Import failed: No module named 'claude_agent_sdk'"
        )

    monkeypatch.setattr("band_wezterm.agent.adapters._claude", boom)
    with pytest.raises(HarnessUnavailableError, match="uv sync --extra claude_sdk"):
        preflight_harness(HarnessId.CLAUDE_SDK)


def test_copilot_passes_reasoning_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeConfig:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakeAdapter:
        def __init__(self, config: object) -> None:
            self.config = config

    adapters_pkg = types.ModuleType("band.adapters")
    adapters_pkg.CopilotSDKAdapter = FakeAdapter  # type: ignore[attr-defined]
    copilot_mod = types.ModuleType("band.adapters.copilot_sdk")
    copilot_mod.CopilotSDKAdapterConfig = FakeConfig  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "band.adapters", adapters_pkg)
    monkeypatch.setitem(
        sys.modules, "band.adapters.copilot_sdk", copilot_mod
    )

    adapter = build_adapter(
        HarnessId.COPILOT_SDK,
        persona="Be terse.",
        tuning=AgentTuning(model="gpt-5.4", reasoning="high"),
    )
    assert isinstance(adapter, FakeAdapter)
    assert captured == {
        "model": "gpt-5.4",
        "reasoning_effort": "high",
        "custom_section": "Be terse.",
    }


def test_claude_passes_persona_and_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeAdapter:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    adapters_pkg = types.ModuleType("band.adapters")
    adapters_pkg.ClaudeSDKAdapter = FakeAdapter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "band.adapters", adapters_pkg)

    adapter = build_adapter(
        HarnessId.CLAUDE_SDK,
        cwd=Path("/tmp/work"),
        persona="# Developer\nBe terse.\n",
        tuning=AgentTuning(model="sonnet", reasoning="off"),
    )
    assert isinstance(adapter, FakeAdapter)
    assert captured == {
        "cwd": "/tmp/work",
        "model": "sonnet",
        "custom_section": "# Developer\nBe terse.\n",
        "max_thinking_tokens": 0,
    }


def test_codex_passes_persona_and_effort(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeConfig:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakeAdapter:
        def __init__(self, config: object) -> None:
            self.config = config

    adapters_pkg = types.ModuleType("band.adapters")
    adapters_pkg.CodexAdapter = FakeAdapter  # type: ignore[attr-defined]
    codex_mod = types.ModuleType("band.adapters.codex")
    codex_mod.CodexAdapterConfig = FakeConfig  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "band.adapters", adapters_pkg)
    monkeypatch.setitem(sys.modules, "band.adapters.codex", codex_mod)

    adapter = build_adapter(
        HarnessId.CODEX,
        persona="# Developer\n",
        tuning=AgentTuning(model="gpt-5.6-sol", reasoning="medium"),
    )
    assert isinstance(adapter, FakeAdapter)
    assert captured == {
        "model": "gpt-5.6-sol",
        "reasoning_effort": "medium",
        "custom_section": "# Developer\n",
    }


def test_persona_omitted_when_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    class FakeAdapter:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    adapters_pkg = types.ModuleType("band.adapters")
    adapters_pkg.ClaudeSDKAdapter = FakeAdapter  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "band.adapters", adapters_pkg)

    build_adapter(HarnessId.CLAUDE_SDK, cwd=Path("/tmp/work"))
    assert "custom_section" not in captured
