"""WezTerm pane identity for managed agent processes."""

from __future__ import annotations

from band_wezterm.identity import (
    AgentRuntime,
    AgentStatus,
    AvatarKind,
    agent_accent,
    harness_badge,
    initials,
    parse_harness,
)
from band_wezterm.osc import OscKey, emit_many_to_stdout


def announce_agent_pane(agent_id: str, name: str, harness: str | None) -> None:
    """Publish managed-agent identity into the current WezTerm pane."""
    fields: dict[OscKey, str] = {
        OscKey.AGENT_ID: agent_id,
        OscKey.AGENT_NAME: name,
        OscKey.AGENT_INITIALS: initials(name),
        OscKey.AGENT_COLOR: agent_accent(agent_id),
        OscKey.AGENT_KIND: AvatarKind.AGENT.value,
        OscKey.AGENT_STATUS: AgentStatus.ONLINE.value,
        OscKey.AGENT_RUNTIME: AgentRuntime.STARTING.value,
    }
    parsed = parse_harness(harness)
    if parsed is not None:
        fields[OscKey.AGENT_HARNESS] = harness_badge(parsed).value
    emit_many_to_stdout(fields)
