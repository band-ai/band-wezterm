"""Per-room git worktrees for the Codex harness (INT-1593).

Codex's ``workspace_for_room`` is called once per room per adapter-process
lifetime and cached by band-sdk-python; a resolver here must therefore be
idempotent — reuse whatever already exists rather than recreating it.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Final

from band.workspaces import WorkspaceResolver

from band_wezterm.config import Settings, load_settings

CODEX_WORKTREES_DIRNAME: Final = "codex-worktrees"
CODEX_WORKTREE_BRANCH_PREFIX: Final = "band-wezterm/codex"
GIT_INIT_CONSENT_MESSAGE: Final = (
    "{cwd} isn't a git repository. Codex needs one to give each room its own "
    "worktree — initialize one here?"
)
GIT_INIT_COMMIT_MESSAGE: Final = "band-wezterm: initial commit"
GIT_INIT_COMMIT_USER_NAME: Final = "band-wezterm"
GIT_INIT_COMMIT_USER_EMAIL: Final = "band-wezterm@localhost"


def codex_worktrees_directory(agent_id: str, settings: Settings | None = None) -> Path:
    return (settings or load_settings()).local_state_directory / CODEX_WORKTREES_DIRNAME / agent_id


def codex_worktree_branch(agent_id: str, room_id: str) -> str:
    # Agent-scoped: git refuses to check out one branch in two worktrees.
    return f"{CODEX_WORKTREE_BRANCH_PREFIX}/{agent_id}/{room_id}"


def _git_on_path() -> bool:
    return shutil.which("git") is not None


def is_git_repo(path: Path) -> bool:
    if not _git_on_path():
        return False
    result = _run_git(path, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _run_git(
    root: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, check=check, capture_output=True, text=True
    )


def _ref_exists(root: Path, ref: str) -> bool:
    result = _run_git(root, "rev-parse", "--verify", "--quiet", ref, check=False)
    return result.returncode == 0


def _worktree_path(worktrees_root: Path, room_id: str) -> Path:
    if not room_id or room_id in {".", ".."}:
        msg = "room_id must be a non-empty path segment"
        raise ValueError(msg)
    if Path(room_id).name != room_id:
        msg = f"room_id must not contain path separators: {room_id!r}"
        raise ValueError(msg)
    worktree = (worktrees_root / room_id).resolve()
    root = worktrees_root.resolve()
    try:
        worktree.relative_to(root)
    except ValueError as error:
        msg = f"room_id escapes worktrees root: {room_id!r}"
        raise ValueError(msg) from error
    return worktree


def create_codex_room_workspace_resolver(repo: Path, agent_id: str) -> WorkspaceResolver:
    repo = repo.resolve()
    toplevel: Path | None = None
    relative_subpath: Path | None = None
    worktrees_root: Path | None = None

    def _worktree_context() -> tuple[Path, Path, Path] | None:
        nonlocal toplevel, relative_subpath, worktrees_root
        # A repo with no commits yet has no HEAD to branch worktrees from.
        if not is_git_repo(repo) or not _ref_exists(repo, "HEAD"):
            return None
        if toplevel is None:
            toplevel = Path(
                _run_git(repo, "rev-parse", "--show-toplevel").stdout.strip()
            ).resolve()
            relative_subpath = (
                Path(".")
                if repo == toplevel
                else repo.relative_to(toplevel)
            )
            worktrees_root = codex_worktrees_directory(agent_id)
        return toplevel, relative_subpath, worktrees_root

    def resolver(room_id: str) -> str:
        context = _worktree_context()
        if context is None:
            return str(repo)
        toplevel_path, subpath, worktrees_root_path = context
        worktree = _worktree_path(worktrees_root_path, room_id)
        if not worktree.is_dir():
            worktree.parent.mkdir(parents=True, exist_ok=True)
            _run_git(toplevel_path, "worktree", "prune", check=False)
            branch = codex_worktree_branch(agent_id, room_id)
            if _ref_exists(toplevel_path, f"refs/heads/{branch}"):
                result = _run_git(
                    toplevel_path, "worktree", "add", str(worktree), branch, check=False
                )
            else:
                result = _run_git(
                    toplevel_path,
                    "worktree",
                    "add",
                    "-b",
                    branch,
                    str(worktree),
                    "HEAD",
                    check=False,
                )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout).strip())
        target = worktree / subpath
        target.mkdir(parents=True, exist_ok=True)
        return str(target)

    return resolver


def remove_codex_worktrees(agent_id: str, settings: Settings | None = None) -> None:
    root = codex_worktrees_directory(agent_id, settings)
    if not root.is_dir():
        return
    for worktree in root.iterdir():
        if worktree.is_dir():
            _run_git(worktree, "worktree", "remove", "--force", str(worktree), check=False)
    shutil.rmtree(root, ignore_errors=True)


def init_git_repo(path: Path) -> None:
    _run_git(path, "init", check=True)
    _run_git(path, "add", "-A", check=True)
    _run_git(
        path,
        "-c",
        f"user.name={GIT_INIT_COMMIT_USER_NAME}",
        "-c",
        f"user.email={GIT_INIT_COMMIT_USER_EMAIL}",
        "commit",
        "--allow-empty",
        "-m",
        GIT_INIT_COMMIT_MESSAGE,
        check=True,
    )


def needs_git_init_consent(cwd: Path, declined_for: str | None) -> bool:
    """Only a decline needs remembering, scoped to that exact directory —
    an accept needs no persistence since ``is_git_repo`` becomes true.

    Never prompts when git is not on PATH (worktrees and init both require it).
    """
    return (
        _git_on_path()
        and not is_git_repo(cwd)
        and str(cwd.resolve()) != declined_for
    )
