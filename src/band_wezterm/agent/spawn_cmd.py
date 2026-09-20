"""Build the WezTerm spawn argv for a managed agent pane."""

from __future__ import annotations

import sys
from pathlib import Path

from band_wezterm.agent.private_files import write_private_text
from band_wezterm.backends import AgentTuning, TuningDimensionId, normalize_tuning
from band_wezterm.client import AgentRecord
from band_wezterm.managed_profiles import ManagedAgentProfile


def write_api_key_file(api_key: str) -> Path:
    """0600 temp file; the agent pane deletes it after reading."""
    return write_private_text(
        content=api_key,
        prefix="band-wezterm-agent-",
        suffix=".key",
    )


def write_persona_file(persona: str) -> Path:
    """0600 temp file for role Markdown — deleted by the agent pane after read."""
    return write_private_text(
        content=persona,
        prefix="band-wezterm-persona-",
        suffix=".md",
    )


def agent_pane_command(
    agent: AgentRecord,
    *,
    key_file: Path,
    cwd: Path,
    profile: ManagedAgentProfile | None = None,
    persona_file: Path | None = None,
) -> list[str]:
    harness = profile.harness if profile is not None else agent.harness
    if harness is None:
        raise ValueError("Agent has no harness — re-register with one.")
    command = [
        sys.executable,
        "-m",
        "band_wezterm.agent",
        "--agent-id",
        agent.id,
        "--harness",
        harness.value,
        "--name",
        agent.name,
        "--key-file",
        str(key_file),
        "--cwd",
        str(cwd),
    ]
    if profile is None:
        return command
    if profile.persona:
        path = persona_file or write_persona_file(profile.persona)
        command.extend(["--persona-file", str(path)])
    tuning = normalize_tuning(harness, profile.tuning)
    model = tuning.value_for(TuningDimensionId.MODEL)
    if model is not None:
        command.extend(["--model", model])
    reasoning = tuning.value_for(TuningDimensionId.REASONING)
    if reasoning is not None:
        command.extend(["--reasoning", reasoning])
    return command


def tuning_from_cli(*, model: str | None, reasoning: str | None) -> AgentTuning:
    return AgentTuning(
        model=model or "",
        reasoning=reasoning or "",
    )
