"""Non-secret local state (starred rooms) — plain JSON, not keyring."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from band_wezterm.config import LOCAL_STATE_DIRNAME


class LocalStateFile(BaseModel):
    model_config = ConfigDict(frozen=True)

    starred: dict[str, list[str]] = Field(default_factory=dict)


def default_state_path() -> Path:
    return Path.home() / LOCAL_STATE_DIRNAME / "local_state.json"


class StarredRooms:
    """Per signed-in user, local-only starred room ids (correction #11)."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or default_state_path()
        self._by_user: dict[str, set[str]] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.exists():
            self._by_user = {}
            return
        try:
            file = LocalStateFile.model_validate_json(
                self._path.read_text(encoding="utf-8")
            )
        except ValidationError:
            self._by_user = {}
            return
        self._by_user = {
            user_id: set(room_ids) for user_id, room_ids in file.starred.items()
        }

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        file = LocalStateFile(
            starred={
                user_id: sorted(room_ids)
                for user_id, room_ids in self._by_user.items()
            }
        )
        self._path.write_text(
            file.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )

    def list(self, user_id: str) -> frozenset[str]:
        return frozenset(self._by_user.get(user_id, set()))

    def is_starred(self, user_id: str, room_id: UUID | str) -> bool:
        return str(room_id) in self._by_user.get(user_id, set())

    def star(self, user_id: str, room_id: UUID | str) -> None:
        self._by_user.setdefault(user_id, set()).add(str(room_id))
        self._save()

    def unstar(self, user_id: str, room_id: UUID | str) -> None:
        rooms = self._by_user.get(user_id)
        if not rooms:
            return
        rooms.discard(str(room_id))
        self._save()

    def toggle(self, user_id: str, room_id: UUID | str) -> bool:
        if self.is_starred(user_id, room_id):
            self.unstar(user_id, room_id)
            return False
        self.star(user_id, room_id)
        return True
