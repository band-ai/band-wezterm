"""Role library — seed, list, create (band-plugin-vsc parity)."""

from __future__ import annotations

from pathlib import Path

from band_wezterm.roles import (
    create_role,
    ensure_role_library,
    list_roles,
    role_file_stem,
    role_name_error,
)


def test_role_file_stem_sanitizes() -> None:
    assert role_file_stem("  UX / UI Designer ") == "ux-ui-designer"


def test_ensure_seeds_defaults_once(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    ensure_role_library(roles_dir)
    names = {path.name for path in roles_dir.glob("*.md")}
    assert "developer.md" in names
    assert "architect.md" in names
    (roles_dir / "developer.md").write_text("# Custom\n", encoding="utf-8")
    ensure_role_library(roles_dir)
    assert (roles_dir / "developer.md").read_text(encoding="utf-8") == "# Custom\n"


def test_list_roles_reads_label_and_description(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    roles_dir.mkdir()
    (roles_dir / "reviewer.md").write_text(
        "---\ndescription: Reviews PRs\n---\n# Reviewer\n\nYou review code.\n",
        encoding="utf-8",
    )
    roles = list_roles(roles_dir)
    assert len(roles) == 1
    assert roles[0].id == "reviewer"
    assert roles[0].label == "Reviewer"
    assert roles[0].description == "Reviews PRs"


def test_create_role_and_duplicate_error(tmp_path: Path) -> None:
    roles_dir = tmp_path / "roles"
    path = create_role("Staff Engineer", roles_dir)
    assert path.name == "staff-engineer.md"
    assert role_name_error("Staff Engineer", roles_dir) is not None
    assert role_name_error("!!!", roles_dir) is not None
