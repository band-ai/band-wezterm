"""Harness adapter factory — one table for CL / CX / CP / OM."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from band_wezterm.backends import AgentTuning, TuningDimensionId, normalize_tuning
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
    try:
        return HarnessId(harness)
    except ValueError as error:
        raise HarnessUnavailableError(f"Unknown harness {harness!r}.") from error


def build_adapter(
    harness: HarnessId | str | None,
    *,
    cwd: Path | None = None,
    persona: str | None = None,
    tuning: AgentTuning | None = None,
    opencode_server_url: str | None = None,
) -> Any:
    """Construct the band-sdk adapter for a harness. Fail loud on missing extras."""
    key = _normalize(harness)
    workdir = str(cwd) if cwd is not None else None
    resolved = normalize_tuning(key, tuning or AgentTuning())
    match key:
        case HarnessId.CLAUDE | HarnessId.CLAUDE_SDK:
            return _claude(workdir, persona=persona, tuning=resolved)
        case HarnessId.CODEX:
            return _codex(persona=persona, tuning=resolved)
        case HarnessId.COPILOT | HarnessId.COPILOT_SDK:
            return _copilot(persona=persona, tuning=resolved)
        case HarnessId.OMP | HarnessId.OPENCODE:
            return _opencode(
                workdir,
                persona=persona,
                tuning=resolved,
                server_url=opencode_server_url,
            )
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


def _claude(
    cwd: str | None,
    *,
    persona: str | None,
    tuning: AgentTuning,
) -> Any:
    try:
        from band.adapters import ClaudeSDKAdapter  # noqa: PLC0415
    except ImportError as error:
        raise _missing(HarnessId.CLAUDE_SDK, error) from error

    kwargs: dict[str, Any] = {"cwd": cwd}
    model = tuning.value_for(TuningDimensionId.MODEL)
    if model is not None:
        kwargs["model"] = model
    _apply_persona(kwargs, persona)
    effort = tuning.value_for(TuningDimensionId.REASONING)
    if effort is not None:
        kwargs["effort"] = effort
    return ClaudeSDKAdapter(**kwargs)


def _apply_persona(kwargs: dict[str, Any], persona: str | None) -> None:
    if persona:
        kwargs["custom_section"] = persona


def _apply_reasoning_effort(config_kwargs: dict[str, Any], tuning: AgentTuning) -> None:
    effort = tuning.value_for(TuningDimensionId.REASONING)
    if effort is not None:
        config_kwargs["reasoning_effort"] = effort


def _codex(*, persona: str | None, tuning: AgentTuning) -> Any:
    try:
        from band.adapters import CodexAdapter  # noqa: PLC0415
        from band.adapters.codex import CodexAdapterConfig  # noqa: PLC0415
    except ImportError as error:
        raise _missing(HarnessId.CODEX, error) from error

    config_kwargs: dict[str, Any] = {}
    model = tuning.value_for(TuningDimensionId.MODEL)
    if model is not None:
        config_kwargs["model"] = model
    _apply_reasoning_effort(config_kwargs, tuning)
    _apply_persona(config_kwargs, persona)
    return CodexAdapter(CodexAdapterConfig(**config_kwargs))


def _copilot(*, persona: str | None, tuning: AgentTuning) -> Any:
    try:
        from band.adapters import CopilotSDKAdapter  # noqa: PLC0415
        from band.adapters.copilot_sdk import CopilotSDKAdapterConfig  # noqa: PLC0415
    except ImportError as error:
        raise _missing(HarnessId.COPILOT_SDK, error) from error

    config_kwargs: dict[str, Any] = {}
    model = tuning.value_for(TuningDimensionId.MODEL)
    if model is not None:
        config_kwargs["model"] = model
    _apply_reasoning_effort(config_kwargs, tuning)
    _apply_persona(config_kwargs, persona)
    return CopilotSDKAdapter(CopilotSDKAdapterConfig(**config_kwargs))


def _opencode(
    directory: str | None,
    *,
    persona: str | None,
    tuning: AgentTuning,
    server_url: str | None,
) -> Any:
    try:
        from band.adapters import OpencodeAdapter  # noqa: PLC0415
        from band.adapters.opencode.config import OpencodeAdapterConfig  # noqa: PLC0415
    except ImportError as error:
        raise _missing(HarnessId.OPENCODE, error) from error

    config_kwargs: dict[str, Any] = {}
    if directory is not None:
        config_kwargs["directory"] = directory
    if server_url is not None:
        config_kwargs["base_url"] = server_url
    model = tuning.value_for(TuningDimensionId.MODEL)
    if model is not None:
        provider_id, separator, model_id = model.partition("/")
        if separator:
            config_kwargs.update(
                provider_id=provider_id,
                model_id=model_id,
            )
        else:
            config_kwargs["model_id"] = model
    variant = tuning.value_for(TuningDimensionId.REASONING)
    if variant is not None:
        config_kwargs["variant"] = variant
    _apply_persona(config_kwargs, persona)
    return OpencodeAdapter(OpencodeAdapterConfig(**config_kwargs))
