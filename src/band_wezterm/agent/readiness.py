"""Validate the local pieces required by a managed agent."""

from __future__ import annotations

from pathlib import Path

from band_wezterm.agent.adapters import preflight_harness
from band_wezterm.backends import AgentTuning
from band_wezterm.identity import HarnessId


def preflight_managed_agent(
    harness: HarnessId,
    *,
    cwd: Path | None = None,
    persona: str | None = None,
    tuning: AgentTuning | None = None,
) -> None:
    """Confirm the detached worker's Band adapter is usable."""
    preflight_harness(harness, cwd=cwd, persona=persona, tuning=tuning)
