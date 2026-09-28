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


def codex_worktrees_directory(agent_id: str, settings: Settings | None = None) -> Path:
    return (settings or load_settings()).local_state_directory / CODEX_WORKTREES_DIRNAME / agent_id


def is_git_repo(path: Path) -> bool:
    result = _run_git(path, "rev-parse", "--is-inside-work-tree", check=False)
    return result.returncode == 0 and result.stdout.strip() == "true"


def _run_git(
    root: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=root, check=check, capture_output=True, text=True
    )


def _branch_exists(root: Path, branch: str) -> bool:
    result = _run_git(root, "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", check=False)
    return result.returncode == 0


def create_codex_room_workspace_resolver(repo: Path, agent_id: str) -> WorkspaceResolver:
    if not is_git_repo(repo):
        shared = str(repo)
        return lambda _room_id, _shared=shared: _shared

    toplevel = Path(_run_git(repo, "rev-parse", "--show-toplevel").stdout.strip())
    relative_subpath = Path(".") if repo == toplevel else repo.relative_to(toplevel)

    def resolver(room_id: str) -> str:
        worktree = codex_worktrees_directory(agent_id) / room_id
        if not worktree.is_dir():
            worktree.parent.mkdir(parents=True, exist_ok=True)
            _run_git(toplevel, "worktree", "prune", check=False)
            branch = f"{CODEX_WORKTREE_BRANCH_PREFIX}/{room_id}"
            if _branch_exists(toplevel, branch):
                result = _run_git(toplevel, "worktree", "add", str(worktree), branch, check=False)
            else:
                result = _run_git(
                    toplevel, "worktree", "add", "-b", branch, str(worktree), "HEAD", check=False
                )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout).strip())
        target = worktree / relative_subpath
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


def needs_git_init_consent(cwd: Path, declined_for: str | None) -> bool:
    """Only a decline needs remembering, scoped to that exact directory —
    an accept needs no persistence since ``is_git_repo`` becomes true."""
    return not is_git_repo(cwd) and str(cwd.resolve()) != declined_for
