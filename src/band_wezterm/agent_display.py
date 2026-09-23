"""Shared, compact presentation of durable managed-agent configuration."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from band_wezterm.agent_draft import role_for_persona
from band_wezterm.backends import (
    TuningDimensionId,
    describe_tuning_value,
    resolve_backend,
)
from band_wezterm.managed_profiles import ManagedAgentProfile


class AgentConfigurationLabel(StrEnum):
    ROLE = "No specific role"
    MODEL = "Adapter default"
    UNMANAGED = "Not managed"
    UNAVAILABLE = "—"


MODEL_DIMENSION: Final = TuningDimensionId.MODEL


@dataclass(frozen=True)
class AgentConfiguration:
    """The small set of durable fields useful when scanning an agent catalog."""

    harness: str
    role: str
    model: str
    options: str


def agent_configuration(profile: ManagedAgentProfile | None) -> AgentConfiguration:
    """Project a local profile without claiming configuration we do not own."""
    if profile is None:
        return AgentConfiguration(
            harness=AgentConfigurationLabel.UNMANAGED,
            role=AgentConfigurationLabel.UNMANAGED,
            model=AgentConfigurationLabel.UNAVAILABLE,
            options=AgentConfigurationLabel.UNAVAILABLE,
        )
    role = role_for_persona(profile.persona)
    return AgentConfiguration(
        harness=resolve_backend(profile.harness).label,
        role=(role.label if role is not None else AgentConfigurationLabel.ROLE),
        model=describe_tuning_value(profile.harness, profile.tuning, MODEL_DIMENSION),
        options=_tuning_options(profile),
    )


def _tuning_options(profile: ManagedAgentProfile) -> str:
    labels = tuple(
        f"{dimension.label}: "
        f"{describe_tuning_value(profile.harness, profile.tuning, dimension.id)}"
        for dimension in resolve_backend(profile.harness).tuning
        if dimension.id is not MODEL_DIMENSION
    )
    return " · ".join(labels) or AgentConfigurationLabel.MODEL
