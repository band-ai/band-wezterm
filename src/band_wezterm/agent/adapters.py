"""Compatibility entrypoints for the central harness registry."""

from __future__ import annotations

from pathlib import Path

from band_wezterm.harnesses.base import AdapterRequest, HarnessUnavailableError
from band_wezterm.harnesses.models import AgentTuning
from band_wezterm.harnesses.registry import DEFAULT_REGISTRY
from band_wezterm.identity import HarnessId


def build_adapter(
    harness: HarnessId | str | None,
    *,
    cwd: Path | None = None,
    persona: str | None = None,
    tuning: AgentTuning | None = None,
    opencode_server_url: str | None = None,
) -> object:
    """Construct the adapter supplied by the selected registered harness."""
    return DEFAULT_REGISTRY.build_adapter(
        harness,
        AdapterRequest(
            cwd=cwd,
            persona=persona,
            tuning=tuning or AgentTuning(),
            opencode_server_url=opencode_server_url,
        ),
    )


def preflight_harness(
    harness: HarnessId | str | None,
    *,
    cwd: Path | None = None,
    persona: str | None = None,
    tuning: AgentTuning | None = None,
) -> None:
    """Verify the provider adapter can be constructed before launching it."""
    build_adapter(harness, cwd=cwd, persona=persona, tuning=tuning)


__all__ = ["HarnessUnavailableError", "build_adapter", "preflight_harness"]
