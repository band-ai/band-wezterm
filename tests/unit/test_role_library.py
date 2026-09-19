"""Role library open/create helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from band_wezterm.role_library import create_and_open_role, open_role_library


def test_open_role_library_seeds_and_reveals(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    revealed: list[Path] = []
    monkeypatch.setattr(
        "band_wezterm.role_library._reveal_path",
        revealed.append,
    )
    roles_dir = tmp_path / "roles"
    opened = open_role_library(roles_dir)
    assert opened == roles_dir
    assert (roles_dir / "developer.md").exists()
    assert revealed == [roles_dir]


def test_create_and_open_role(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[Path] = []
    monkeypatch.setattr(
        "band_wezterm.role_library._open_file",
        opened.append,
    )
    path = create_and_open_role("Staff Engineer", tmp_path / "roles")
    assert path.name == "staff-engineer.md"
    assert path.exists()
    assert opened == [path]


def test_create_and_open_role_rejects_duplicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("band_wezterm.role_library._open_file", MagicMock())
    create_and_open_role("Dup", tmp_path / "roles")
    with pytest.raises(ValueError, match="already exists"):
        create_and_open_role("Dup", tmp_path / "roles")
