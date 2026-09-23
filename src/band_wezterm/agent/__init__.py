"""Managed-agent runtime package.

The package deliberately avoids importing adapter providers: screens can use
the local OpenCode service without loading every optional harness dependency.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from band_wezterm.agent.adapters import HarnessUnavailableError


def __getattr__(name: str) -> object:
    match name:
        case "HarnessUnavailableError" | "build_adapter" | "preflight_harness":
            from band_wezterm.agent import adapters  # noqa: PLC0415 - lazy API

            return getattr(adapters, name)
        case "main":
            from band_wezterm.agent.runner import main  # noqa: PLC0415 - lazy API

            return main
        case _:
            raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["HarnessUnavailableError", "build_adapter", "main", "preflight_harness"]
