"""WezTerm pane identity OSC — shared by Control host and agent panes."""

from __future__ import annotations

from typing import Final

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

CONTROL_HUMAN_NAME: Final = "You"
BACKGROUND_ENABLED: Final = "1"
BACKGROUND_DISABLED: Final = "0"


def pane_identity_fields(
    subject_id: str,
    name: str,
    *,
    kind: AvatarKind,
    status: AgentStatus = AgentStatus.ONLINE,
    runtime: AgentRuntime | None = None,
    harness: str | None = None,
) -> dict[OscKey, str]:
    """Allowlisted OSC fields for one WezTerm pane (human or agent)."""
    fields: dict[OscKey, str] = {
        OscKey.AGENT_ID: subject_id,
        OscKey.AGENT_NAME: name,
        OscKey.AGENT_INITIALS: initials(name),
        OscKey.AGENT_COLOR: agent_accent(subject_id),
        OscKey.AGENT_KIND: kind.value,
        OscKey.AGENT_STATUS: status.value,
    }
    if runtime is not None:
        fields[OscKey.AGENT_RUNTIME] = runtime.value
    parsed = parse_harness(harness)
    if parsed is not None:
        fields[OscKey.AGENT_HARNESS] = harness_badge(parsed).value
    return fields


def agent_identity_fields(
    agent_id: str,
    name: str,
    harness: str | None,
    *,
    runtime: AgentRuntime = AgentRuntime.STARTING,
) -> dict[OscKey, str]:
    """Allowlisted OSC fields for one managed-agent pane."""
    return pane_identity_fields(
        agent_id,
        name,
        kind=AvatarKind.AGENT,
        runtime=runtime,
        harness=harness,
    )


def announce_pane(
    subject_id: str,
    name: str,
    *,
    kind: AvatarKind,
    status: AgentStatus = AgentStatus.ONLINE,
    runtime: AgentRuntime | None = None,
    harness: str | None = None,
) -> None:
    """Publish identity into the current WezTerm pane's stdout."""
    emit_many_to_stdout(
        pane_identity_fields(
            subject_id,
            name,
            kind=kind,
            status=status,
            runtime=runtime,
            harness=harness,
        )
    )


def announce_agent_pane(
    agent_id: str,
    name: str,
    harness: str | None,
    *,
    runtime: AgentRuntime = AgentRuntime.STARTING,
) -> None:
    """Publish managed-agent identity into the current WezTerm pane."""
    announce_pane(
        agent_id,
        name,
        kind=AvatarKind.AGENT,
        runtime=runtime,
        harness=harness,
    )


def announce_human_pane(user_id: str, name: str = CONTROL_HUMAN_NAME) -> None:
    """Publish the signed-in Control human into the current WezTerm pane."""
    announce_pane(user_id, name, kind=AvatarKind.HUMAN)


def announce_control_human(user_id: str) -> None:
    """Control-tab host identity (display name ``CONTROL_HUMAN_NAME``)."""
    announce_human_pane(user_id, CONTROL_HUMAN_NAME)


def announce_control_preferences(*, show_band_background: bool) -> None:
    """Publish Control-only presentation preferences into its WezTerm pane."""
    emit_many_to_stdout(
        {
            OscKey.BACKGROUND_ENABLED: (
                BACKGROUND_ENABLED if show_band_background else BACKGROUND_DISABLED
            )
        }
    )


def announce_runtime_status(
    runtime: AgentRuntime, status: AgentStatus = AgentStatus.OFFLINE
) -> None:
    """Update runtime/status only (error, stopping, offline)."""
    emit_many_to_stdout(
        {
            OscKey.AGENT_RUNTIME: runtime.value,
            OscKey.AGENT_STATUS: status.value,
        }
    )
