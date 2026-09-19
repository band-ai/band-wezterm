"""Managed agent profiles — local persona + tuning keyed by agent id (INT-1484)."""

from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from band_wezterm.backends import AgentTuning
from band_wezterm.config import LOCAL_STATE_DIRNAME
from band_wezterm.identity import HarnessId, parse_harness

_PROFILE_SAVE_TMP_PREFIX: Final = ".managed_agents."
_PROFILE_SAVE_TMP_SUFFIX: Final = ".tmp"


class ManagedAgentProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    agent_id: str
    name: str
    harness: HarnessId
    persona: str | None = None
    tuning: AgentTuning = Field(default_factory=AgentTuning)


class _ProfilesFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    profiles: list[ManagedAgentProfile] = Field(default_factory=list)


def default_profiles_path() -> Path:
    return Path.home() / LOCAL_STATE_DIRNAME / "managed_agents.json"


class ManagedAgentStore:
    """Durable launch profile — independent of keyring credentials."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_profiles_path()
        self._profiles: dict[str, ManagedAgentProfile] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._profiles = {}
            return
        try:
            file = _ProfilesFile.model_validate_json(
                self._path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError):
            self._profiles = {}
            return
        self._profiles = {profile.agent_id: profile for profile in file.profiles}

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        file = _ProfilesFile(profiles=sorted(self._profiles.values(), key=lambda p: p.agent_id))
        content = file.model_dump_json(indent=2) + "\n"
        fd, tmp_name = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=_PROFILE_SAVE_TMP_PREFIX,
            suffix=_PROFILE_SAVE_TMP_SUFFIX,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_name, self._path)
        except Exception:
            with suppress(OSError):
                Path(tmp_name).unlink(missing_ok=True)
            raise

    def record(self, profile: ManagedAgentProfile) -> None:
        previous = self._profiles.get(profile.agent_id)
        self._profiles[profile.agent_id] = profile
        try:
            self._save()
        except Exception:
            if previous is None:
                self._profiles.pop(profile.agent_id, None)
            else:
                self._profiles[profile.agent_id] = previous
            raise

    def get(self, agent_id: str) -> ManagedAgentProfile | None:
        return self._profiles.get(agent_id)

    def remove(self, agent_id: str) -> None:
        previous = self._profiles.pop(agent_id, None)
        if previous is None:
            return
        try:
            self._save()
        except Exception:
            self._profiles[agent_id] = previous
            raise

    def list(self) -> tuple[ManagedAgentProfile, ...]:
        return tuple(sorted(self._profiles.values(), key=lambda p: p.name.lower()))

    def set_persona_and_tuning(
        self,
        agent_id: str,
        *,
        persona: str | None,
        tuning: AgentTuning,
    ) -> None:
        existing = self._profiles.get(agent_id)
        if existing is None:
            return
        self._profiles[agent_id] = existing.model_copy(
            update={"persona": persona, "tuning": tuning}
        )
        self._save()

    def harness_for(self, agent_id: str) -> HarnessId | None:
        profile = self._profiles.get(agent_id)
        return None if profile is None else profile.harness


def profile_from_registration(
    *,
    agent_id: str,
    name: str,
    harness: HarnessId | str,
    persona: str | None,
    tuning: AgentTuning,
) -> ManagedAgentProfile:
    parsed = parse_harness(harness)
    if parsed is None:
        raise ValueError(f"Unknown harness {harness!r}")
    return ManagedAgentProfile(
        agent_id=agent_id,
        name=name,
        harness=parsed,
        persona=persona,
        tuning=tuning,
    )
