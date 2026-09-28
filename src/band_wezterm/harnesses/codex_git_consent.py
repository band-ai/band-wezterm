"""Codex git-init consent shared by CLI and TUI start paths."""

from __future__ import annotations

from pathlib import Path

from band_wezterm.harnesses.codex_worktrees import (
    GIT_INIT_CONSENT_MESSAGE,
    init_git_repo,
    needs_git_init_consent,
)
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import ManagedAgentStore

__all__ = (
    "GIT_INIT_CONSENT_MESSAGE",
    "apply_codex_git_init_consent",
    "codex_wants_git_init_consent",
)


def codex_wants_git_init_consent(
    harness: HarnessId, cwd: Path, declined_for: str | None
) -> bool:
    return harness is HarnessId.CODEX and needs_git_init_consent(cwd, declined_for)


def apply_codex_git_init_consent(
    profiles: ManagedAgentStore,
    agent_id: str,
    cwd: Path,
    *,
    granted: bool,
) -> None:
    if granted:
        init_git_repo(cwd)
    else:
        profiles.set_git_init_declined(agent_id, cwd)
