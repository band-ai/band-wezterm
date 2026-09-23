"""Shared parsing for detached worker tuning."""

from __future__ import annotations

from band_wezterm.backends import AgentTuning


def tuning_from_cli(*, model: str | None, reasoning: str | None) -> AgentTuning:
    """Normalize optional worker CLI values into the durable tuning shape."""
    return AgentTuning(model=model or "", reasoning=reasoning or "")
