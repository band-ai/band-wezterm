"""Harness adapter factory — one table for CL / CX / CP / OM."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from band_wezterm.identity import HarnessId

_MISSING_EXTRA: dict[HarnessId, str] = {
    HarnessId.CLAUDE: "claude_sdk",
    HarnessId.CLAUDE_SDK: "claude_sdk",
    HarnessId.CODEX: "codex",
    HarnessId.COPILOT: "copilot_sdk",
    HarnessId.COPILOT_SDK: "copilot_sdk",
    HarnessId.OMP: "opencode",
    HarnessId.OPENCODE: "opencode",
}

# Published band-sdk Provides-Extra names (hyphenated).
_SDK_EXTRA: dict[str, str] = {
    "claude_sdk": "claude-sdk",
    "codex": "codex",
    "copilot_sdk": "copilot-sdk",
    "opencode": "opencode",
}


class HarnessUnavailableError(RuntimeError):
    """Raised when the adapter extra is not installed or harness is unknown."""


def _normalize(harness: HarnessId | str | None) -> HarnessId:
    if harness is None:
        raise HarnessUnavailableError("Agent has no harness — re-register with one.")
    if isinstance(harness, HarnessId):
        return harness
    try:
        return HarnessId(harness)
    except ValueError as error:
        raise HarnessUnavailableError(f"Unknown harness {harness!r}.") from error


def build_adapter(harness: HarnessId | str | None, *, cwd: Path | None = None) -> Any:
    """Construct the band-sdk adapter for a harness. Fail loud on missing extras."""
    key = _normalize(harness)
    workdir = str(cwd) if cwd is not None else None
    match key:
        case HarnessId.CLAUDE | HarnessId.CLAUDE_SDK:
            return _claude(workdir)
        case HarnessId.CODEX:
            return _codex()
        case HarnessId.COPILOT | HarnessId.COPILOT_SDK:
            return _copilot()
        case HarnessId.OMP | HarnessId.OPENCODE:
            return _opencode()
        case _:
            raise HarnessUnavailableError(f"Unsupported harness {key.value!r}.")


def preflight_harness(harness: HarnessId | str | None) -> None:
    """Import-check the adapter extra before spawning a pane."""
    build_adapter(harness)


def _missing(key: HarnessId, error: Exception) -> HarnessUnavailableError:
    host_extra = _MISSING_EXTRA[key]
    sdk_extra = _SDK_EXTRA[host_extra]
    return HarnessUnavailableError(
        f"Harness {key.value} requires `uv sync --extra {host_extra}` "
        f"(or `--extra agents`; installs band-sdk[{sdk_extra}]). "
        f"Import failed: {error}"
    )


def _claude(cwd: str | None) -> Any:
    try:
        from band.adapters import ClaudeSDKAdapter  # noqa: PLC0415

        return ClaudeSDKAdapter(cwd=cwd)
    except ImportError as error:
        raise _missing(HarnessId.CLAUDE_SDK, error) from error


def _codex() -> Any:
    try:
        from band.adapters import CodexAdapter  # noqa: PLC0415

        return CodexAdapter()
    except ImportError as error:
        raise _missing(HarnessId.CODEX, error) from error


def _copilot() -> Any:
    try:
        from band.adapters import CopilotSDKAdapter  # noqa: PLC0415

        return CopilotSDKAdapter()
    except ImportError as error:
        raise _missing(HarnessId.COPILOT_SDK, error) from error


def _opencode() -> Any:
    try:
        from band.adapters import OpencodeAdapter  # noqa: PLC0415

        return OpencodeAdapter()
    except ImportError as error:
        raise _missing(HarnessId.OPENCODE, error) from error
