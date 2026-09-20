"""Agent registration draft — harness, role, name, description, tuning."""

from __future__ import annotations

import re
import secrets
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from band_wezterm.backends import (
    DEFAULT_HARNESS,
    AgentTuning,
    resolve_backend,
)
from band_wezterm.identity import HarnessId
from band_wezterm.roles import Role, list_roles

# Platform contract (`Agent.max` name length + `[^@/]`). Matches VSC `agentNaming.ts`.
AGENT_NAME_MIN: Final = 3
AGENT_NAME_MAX: Final = 100
AGENT_DESCRIPTION_MIN: Final = 10
AGENT_DESCRIPTION_MAX: Final = 500
DEFAULT_AGENT_DESCRIPTION: Final = "Added via the Band WezTerm host."
NO_ROLE_LABEL: Final = "No specific role"
CUSTOM_ROLE_LABEL: Final = "Custom"
NAME_FORBIDDEN_MESSAGE: Final = "Name must not contain @ or / characters."
_FORBIDDEN_NAME_CHARACTERS: Final = re.compile(r"[@/]")
_WHITESPACE: Final = re.compile(r"\s+")
_SUFFIX_ALPHABET: Final = "0123456789abcdefghijklmnopqrstuvwxyz"
_SUFFIX_LENGTH: Final = 6


def unique_suffix() -> str:
    return "".join(secrets.choice(_SUFFIX_ALPHABET) for _ in range(_SUFFIX_LENGTH))


class AgentDraft(BaseModel):
    """Everything the register flow collects before calling the platform."""

    model_config = ConfigDict(frozen=True)

    harness: HarnessId = DEFAULT_HARNESS
    role: Role | None = None
    name: str | None = None
    name_suffix: str = Field(default_factory=unique_suffix)
    description: str = DEFAULT_AGENT_DESCRIPTION
    tuning: AgentTuning = Field(default_factory=AgentTuning)


def create_default_draft() -> AgentDraft:
    return AgentDraft()


def apply_draft_patch(draft: AgentDraft, **patch: object) -> AgentDraft:
    """Apply one field edit. Changing harness resets tuning (vocab differs)."""
    next_draft = draft.model_copy(update=patch)
    if next_draft.harness is draft.harness:
        return next_draft
    return next_draft.model_copy(update={"tuning": AgentTuning()})


def suggested_agent_name(label: str, suffix: str) -> str:
    """Role/runtime label plus suffix, stripped of characters the platform rejects."""
    room = AGENT_NAME_MAX - len(suffix) - (1 if suffix else 0)
    sanitized = _WHITESPACE.sub(
        " ", _FORBIDDEN_NAME_CHARACTERS.sub(" ", label)
    ).strip()
    head = sanitized[:room].strip() if room > 0 else ""
    if not suffix:
        return head
    if not head:
        return suffix
    return f"{head} {suffix}"


def draft_name(draft: AgentDraft) -> str:
    if draft.name:
        return draft.name
    seed = (
        draft.role.label
        if draft.role is not None
        else resolve_backend(draft.harness).label
    )
    return suggested_agent_name(seed, draft.name_suffix)


def agent_name_error(name: str) -> str | None:
    trimmed = name.strip()
    if not trimmed:
        return "Name is required."
    if len(trimmed) < AGENT_NAME_MIN:
        return f"Name must be at least {AGENT_NAME_MIN} characters."
    if len(trimmed) > AGENT_NAME_MAX:
        return f"Name must be at most {AGENT_NAME_MAX} characters."
    if _FORBIDDEN_NAME_CHARACTERS.search(trimmed):
        return NAME_FORBIDDEN_MESSAGE
    return None


def length_error(label: str, trimmed: str, *, min_len: int, max_len: int) -> str | None:
    if len(trimmed) < min_len:
        return f"{label} must be at least {min_len} characters."
    if len(trimmed) > max_len:
        return f"{label} must be at most {max_len} characters."
    return None


def description_error(description: str) -> str | None:
    return length_error(
        "Description",
        description.strip(),
        min_len=AGENT_DESCRIPTION_MIN,
        max_len=AGENT_DESCRIPTION_MAX,
    )


def role_for_persona(
    persona: str | None, roles_dir: Path | str | None = None
) -> Role | None:
    if persona is None:
        return None
    return next(
        (role for role in list_roles(roles_dir) if role.content == persona),
        Role(id="", label=CUSTOM_ROLE_LABEL, content=persona),
    )


def draft_from_profile(
    *,
    name: str,
    harness: HarnessId,
    persona: str | None,
    tuning: AgentTuning,
    roles_dir: Path | str | None = None,
) -> AgentDraft:
    return AgentDraft(
        harness=harness,
        role=role_for_persona(persona, roles_dir),
        name=name,
        name_suffix="",
        description=DEFAULT_AGENT_DESCRIPTION,
        tuning=tuning,
    )
