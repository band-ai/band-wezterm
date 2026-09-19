"""Harness adapter factory — mapping and missing-extra errors."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from band_wezterm.agent.adapters import (
    HarnessUnavailableError,
    build_adapter,
    preflight_harness,
)
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
    def boom(_cwd: str | None = None) -> None:
        raise HarnessUnavailableError(
            "Harness claude_sdk requires `uv sync --extra claude_sdk` "
            "(or `--extra agents`; installs band-sdk[claude-sdk]). "
            "Import failed: No module named 'claude_agent_sdk'"
        )

    monkeypatch.setattr("band_wezterm.agent.adapters._claude", boom)
    with pytest.raises(HarnessUnavailableError, match="uv sync --extra claude_sdk"):
        preflight_harness(HarnessId.CLAUDE_SDK)
