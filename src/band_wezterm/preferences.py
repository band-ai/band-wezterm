"""Host preferences that alter an active Band view."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator

from band_wezterm.config import CHAT_MESSAGES_LIMIT, Settings, load_settings
from band_wezterm.local_storage import atomic_write_text
from band_wezterm.tui.chat_events import DEFAULT_ALLOWED_TYPES, normalize_allowed_types

MIN_CHAT_MESSAGES_LIMIT = 1
MAX_CHAT_MESSAGES_LIMIT = 100


class HostPreferences(BaseModel):
    """Local-only Band settings — not secrets, not platform config."""

    model_config = ConfigDict(frozen=True)

    chat_messages_limit: int = CHAT_MESSAGES_LIMIT
    chat_event_types: tuple[str, ...] = DEFAULT_ALLOWED_TYPES
    show_band_background: bool = False

    @field_validator("chat_messages_limit")
    @classmethod
    def _chat_limit(cls, value: int) -> int:
        if not MIN_CHAT_MESSAGES_LIMIT <= value <= MAX_CHAT_MESSAGES_LIMIT:
            raise ValueError(
                f"chat_messages_limit must be {MIN_CHAT_MESSAGES_LIMIT}-{MAX_CHAT_MESSAGES_LIMIT}"
            )
        return value

    @field_validator("chat_event_types", mode="before")
    @classmethod
    def _chat_event_types(cls, value: object) -> tuple[str, ...]:
        if value is None:
            return DEFAULT_ALLOWED_TYPES
        if isinstance(value, str):
            return normalize_allowed_types([value])
        if isinstance(value, (list, tuple, set, frozenset)):
            return normalize_allowed_types(str(item) for item in value)
        raise TypeError("chat_event_types must be a sequence of strings")


def default_preferences_path(settings: Settings | None = None) -> Path:
    return (settings or load_settings()).local_state_path("preferences.json")


class PreferencesStore:
    def __init__(
        self, path: Path | None = None, *, settings: Settings | None = None
    ) -> None:
        self._path = path or default_preferences_path(settings)
        self._prefs = HostPreferences()
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            self._prefs = HostPreferences.model_validate_json(
                self._path.read_text(encoding="utf-8")
            )
        except (OSError, ValidationError):
            self._prefs = HostPreferences()

    def _save(self) -> None:
        atomic_write_text(self._path, self._prefs.model_dump_json(indent=2) + "\n")

    @property
    def current(self) -> HostPreferences:
        return self._prefs

    def update(self, **patch: object) -> HostPreferences:
        self._prefs = self._prefs.model_copy(update=patch)
        self._save()
        return self._prefs
