"""Harness adapter factory — mapping and missing-extra errors."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from band_wezterm.agent.adapters import build_adapter
from band_wezterm.catalogs import HarnessCatalog
from band_wezterm.harnesses.base import AdapterRequest, HarnessProvider
from band_wezterm.harnesses.models import AgentTuning, HarnessBackend
from band_wezterm.harnesses.registry import HarnessRegistry
from band_wezterm.identity import HarnessId


class _ExampleHarness(HarnessProvider):
    backend = HarnessBackend(harness=HarnessId.CODEX, label="Example", badge="EX")
    aliases = (HarnessId.CLAUDE,)

    def __init__(self) -> None:
        self.request: AdapterRequest | None = None

    def build_adapter(self, request: AdapterRequest) -> object:
        self.request = request
        return self

    async def load_catalog(self, server: object) -> HarnessCatalog:
        del server
        return HarnessCatalog(models=())


def test_harness_registry_uses_one_provider_for_its_aliases() -> None:
    provider = _ExampleHarness()
    registry = HarnessRegistry((provider,))

    assert registry.build_adapter(HarnessId.CLAUDE, AdapterRequest()) is provider
    assert provider.request is not None
    assert registry.resolve(HarnessId.CLAUDE) is provider


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
    monkeypatch.setitem(sys.modules, "band.adapters.copilot_sdk", copilot_mod)

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


def test_claude_passes_only_bridge_supported_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        tuning=AgentTuning(model="sonnet", reasoning="xhigh"),
    )
    assert isinstance(adapter, FakeAdapter)
    assert captured == {
        "cwd": str(Path("/tmp/work")),
        "model": "sonnet",
        "custom_section": "# Developer\nBe terse.\n",
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


def test_opencode_uses_shared_server_and_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeConfig:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

    class FakeAdapter:
        def __init__(self, config: object) -> None:
            self.config = config

    adapters_pkg = types.ModuleType("band.adapters")
    adapters_pkg.OpencodeAdapter = FakeAdapter  # type: ignore[attr-defined]
    config_mod = types.ModuleType("band.adapters.opencode.config")
    config_mod.OpencodeAdapterConfig = FakeConfig  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "band.adapters", adapters_pkg)
    monkeypatch.setitem(sys.modules, "band.adapters.opencode.config", config_mod)

    adapter = build_adapter(
        HarnessId.OPENCODE,
        cwd=Path("/tmp/work"),
        persona="Be precise.",
        tuning=AgentTuning(model="provider/model", reasoning="high"),
        opencode_server_url="http://127.0.0.1:43117",
    )

    assert isinstance(adapter, FakeAdapter)
    assert captured == {
        "directory": str(Path("/tmp/work")),
        "base_url": "http://127.0.0.1:43117",
        "provider_id": "provider",
        "model_id": "model",
        "variant": "high",
        "custom_section": "Be precise.",
    }
