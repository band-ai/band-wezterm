"""Validate the local pieces required by a managed agent."""

from __future__ import annotations

from pathlib import Path

from band_wezterm.agent.adapters import preflight_harness
from band_wezterm.agent.native_console import preflight_native_console
from band_wezterm.backends import AgentTuning
from band_wezterm.identity import HarnessId


def preflight_managed_agent(
    harness: HarnessId,
    *,
    cwd: Path | None = None,
    persona: str | None = None,
    tuning: AgentTuning | None = None,
    require_native_console: bool = False,
) -> None:
    """Confirm the Band adapter — and optionally the private native console — are usable."""
    preflight_harness(harness, cwd=cwd, persona=persona, tuning=tuning)
    if require_native_console:
        preflight_native_console(harness)
