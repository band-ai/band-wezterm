"""Agent pane runtime — band-sdk adapters in a WezTerm tab."""

from __future__ import annotations

from band_wezterm.agent.adapters import (
    HarnessUnavailableError,
    build_adapter,
    preflight_harness,
)
from band_wezterm.agent.runner import main

__all__ = [
    "HarnessUnavailableError",
    "build_adapter",
    "main",
    "preflight_harness",
]
