"""Per-room git worktrees for the Codex harness (INT-1593)."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from band_wezterm.harnesses.codex_worktrees import (
    CODEX_WORKTREE_BRANCH_PREFIX,
    codex_worktrees_directory,
    create_codex_room_workspace_resolver,
    init_git_repo,
    is_git_repo,
    needs_git_init_consent,
    remove_codex_worktrees,
)

AGENT_ID = "agent-1"


def _git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, check=check, capture_output=True, text=True
    )


def _init_repo(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    _git(root, "init")
    (root / "README.md").write_text("hello\n", encoding="utf-8")
    _git(root, "add", "README.md")
    _git(
        root,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@localhost",
        "commit",
        "-m",
        "initial",
    )
    return root


def _branch_of(worktree: Path) -> str:
    return _git(worktree, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()


@pytest.fixture(autouse=True)
def _home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    return home


def test_two_rooms_get_two_isolated_worktrees(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    resolver = create_codex_room_workspace_resolver(repo, AGENT_ID)

    path_a = Path(resolver("room-a"))
    path_b = Path(resolver("room-b"))

    assert path_a != path_b
    assert path_a.is_dir()
    assert path_b.is_dir()
    assert _branch_of(path_a) == f"{CODEX_WORKTREE_BRANCH_PREFIX}/room-a"
    assert _branch_of(path_b) == f"{CODEX_WORKTREE_BRANCH_PREFIX}/room-b"


def test_resolver_is_idempotent_for_the_same_room(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    resolver = create_codex_room_workspace_resolver(repo, AGENT_ID)

    first = Path(resolver("room-a"))
    (first / "in-progress.txt").write_text("draft\n", encoding="utf-8")

    second = Path(resolver("room-a"))

    assert second == first
    assert (second / "in-progress.txt").read_text(encoding="utf-8") == "draft\n"


def test_resolver_recovers_from_an_externally_deleted_worktree(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    resolver = create_codex_room_workspace_resolver(repo, AGENT_ID)

    first = Path(resolver("room-a"))
    shutil.rmtree(first)

    second = Path(resolver("room-a"))

    assert second == first
    assert second.is_dir()
    assert _branch_of(second) == f"{CODEX_WORKTREE_BRANCH_PREFIX}/room-a"


def test_remove_codex_worktrees_clears_everything_but_keeps_branches(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    resolver = create_codex_room_workspace_resolver(repo, AGENT_ID)
    resolver("room-a")
    resolver("room-b")
    root = codex_worktrees_directory(AGENT_ID)
    assert root.is_dir()

    remove_codex_worktrees(AGENT_ID)

    assert not root.exists()
    branches = _git(repo, "branch", "--list").stdout
    assert f"{CODEX_WORKTREE_BRANCH_PREFIX}/room-a" in branches
    assert f"{CODEX_WORKTREE_BRANCH_PREFIX}/room-b" in branches


def test_remove_codex_worktrees_is_a_noop_when_nothing_was_ever_created() -> None:
    remove_codex_worktrees(AGENT_ID)


def test_launch_subdirectory_gets_the_equivalent_subdirectory_in_the_worktree(
    tmp_path: Path,
) -> None:
    repo = _init_repo(tmp_path / "repo")
    subdir = repo / "packages" / "app"
    subdir.mkdir(parents=True)
    (subdir / "marker.txt").write_text("here\n", encoding="utf-8")
    _git(repo, "add", "packages/app/marker.txt")
    _git(
        repo,
        "-c",
        "user.name=test",
        "-c",
        "user.email=test@localhost",
        "commit",
        "-m",
        "add subdir",
    )
    resolver = create_codex_room_workspace_resolver(subdir, AGENT_ID)

    resolved = Path(resolver("room-a"))

    assert resolved == codex_worktrees_directory(AGENT_ID) / "room-a" / "packages" / "app"
    assert (resolved / "marker.txt").is_file()


def test_non_git_directory_falls_back_to_a_shared_workspace(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    resolver = create_codex_room_workspace_resolver(plain, AGENT_ID)

    assert resolver("room-a") == str(plain)
    assert resolver("room-b") == str(plain)


def test_init_git_repo_makes_is_git_repo_true(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()
    assert not is_git_repo(plain)

    init_git_repo(plain)

    assert is_git_repo(plain)


def test_init_git_repo_allows_worktree_creation(tmp_path: Path) -> None:
    plain = tmp_path / "plain"
    plain.mkdir()

    init_git_repo(plain)
    resolver = create_codex_room_workspace_resolver(plain, AGENT_ID)

    path = Path(resolver("room-a"))

    assert path.is_dir()
    assert _branch_of(path) == f"{CODEX_WORKTREE_BRANCH_PREFIX}/room-a"


def test_resolver_rejects_path_traversal_room_id(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    resolver = create_codex_room_workspace_resolver(repo, AGENT_ID)

    with pytest.raises(ValueError, match="path separators"):
        resolver("../evil")

    with pytest.raises(ValueError, match="path separators"):
        resolver("room/nested")


def test_needs_git_init_consent_is_scoped_to_the_declined_directory(
    tmp_path: Path,
) -> None:
    non_git = tmp_path / "non-git"
    non_git.mkdir()
    other_non_git = tmp_path / "other-non-git"
    other_non_git.mkdir()
    git_repo = _init_repo(tmp_path / "repo")

    assert needs_git_init_consent(non_git, None)
    assert not needs_git_init_consent(non_git, str(non_git.resolve()))
    assert needs_git_init_consent(other_non_git, str(non_git.resolve()))
    assert not needs_git_init_consent(git_repo, None)
    assert not needs_git_init_consent(git_repo, str(non_git.resolve()))
