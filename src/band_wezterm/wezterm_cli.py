"""wezterm cli wrapper — first-spawn vs window-id rule (correction #1)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Mapping

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError

from band_wezterm.config import BAND_WORKSPACE_NAME


class WindowId(RootModel[int]):
    model_config = ConfigDict(frozen=True)


class PaneId(RootModel[int]):
    model_config = ConfigDict(frozen=True)


class SpawnResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    window_id: WindowId
    pane_id: PaneId


class PaneInfo(BaseModel):
    """Typed row from `wezterm cli list --format json`."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    window_id: int
    pane_id: int
    workspace: str | None = None
    title: str | None = None
    cwd: str | None = None


class WezTermCliError(RuntimeError):
    """Base for wezterm CLI failures (missing binary or nonzero exit)."""


class WezTermNotFoundError(WezTermCliError):
    pass


def pane_command_env(
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Environment for programs we spawn into WezTerm panes.

    Strips ``NO_COLOR`` / ``FORCE_COLOR=0`` so Textual does not go monochrome
    when the launcher shell exported them (common in agent/CI environments).
    """
    env = dict(os.environ if base is None else base)
    env.pop("NO_COLOR", None)
    if env.get("FORCE_COLOR") == "0":
        env.pop("FORCE_COLOR", None)
    env.setdefault("COLORTERM", "truecolor")
    if env.get("TERM") in (None, "", "dumb"):
        env["TERM"] = "xterm-256color"
    return env


def _wezterm_bin() -> str:
    path = shutil.which("wezterm")
    if path is None:
        raise WezTermNotFoundError("wezterm not found on PATH")
    return path


def _run(args: list[str], *, env: Mapping[str, str] | None = None) -> str:
    completed = subprocess.run(
        [_wezterm_bin(), *args],
        check=False,
        capture_output=True,
        text=True,
        env=dict(env) if env is not None else None,
    )
    if completed.returncode != 0:
        raise WezTermCliError(
            f"wezterm {' '.join(args)} failed ({completed.returncode}): "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def spawn_first_tab(cwd: Path, command: list[str]) -> SpawnResult:
    """Open the `band` workspace with the Control tab as the first pane.

    Correction #1: `--workspace` only works with `--new-window`, and is mutually
    exclusive with `--window-id`. Capture the returned pane id, then resolve
    its window id via `list`.
    """
    stdout = _run(
        [
            "cli",
            "spawn",
            "--new-window",
            "--workspace",
            BAND_WORKSPACE_NAME,
            "--cwd",
            str(cwd),
            "--",
            *command,
        ]
    )
    pane_id = PaneId(int(stdout.splitlines()[-1].strip()))
    window_id = _window_id_for_pane(pane_id)
    return SpawnResult(window_id=window_id, pane_id=pane_id)


def spawn_additional_tab(
    window_id: WindowId, cwd: Path, command: list[str]
) -> PaneId:
    """Spawn a subsequent tab into an existing `band` window (correction #1)."""
    stdout = _run(
        [
            "cli",
            "spawn",
            "--window-id",
            str(window_id.root),
            "--cwd",
            str(cwd),
            "--",
            *command,
        ]
    )
    return PaneId(int(stdout.splitlines()[-1].strip()))


def kill_pane(pane_id: PaneId) -> None:
    _run(["cli", "kill-pane", "--pane-id", str(pane_id.root)])


def set_tab_title(pane_id: PaneId, title: str) -> None:
    """Name the tab that owns ``pane_id`` (visible in the tab bar)."""
    _run(
        [
            "cli",
            "set-tab-title",
            "--pane-id",
            str(pane_id.root),
            title,
        ]
    )


def send_text(pane_id: PaneId, text: str) -> None:
    _run(
        [
            "cli",
            "send-text",
            "--no-paste",
            "--pane-id",
            str(pane_id.root),
            text,
        ]
    )


def list_panes(*, env: Mapping[str, str] | None = None) -> list[PaneInfo]:
    stdout = _run(["cli", "list", "--format", "json"], env=env)
    if not stdout:
        return []
    payload = json.loads(stdout)
    if not isinstance(payload, list):
        raise WezTermCliError("wezterm cli list returned non-list JSON")
    try:
        return [PaneInfo.model_validate(entry) for entry in payload]
    except ValidationError as error:
        raise WezTermCliError(f"wezterm cli list JSON failed validation: {error}") from error


def window_id_for_pane(pane_id: PaneId) -> WindowId:
    """Resolve a pane's window — the Control tab uses it to find its own."""
    return _window_id_for_pane(pane_id)


def _window_id_for_pane(pane_id: PaneId) -> WindowId:
    for entry in list_panes():
        if entry.pane_id == pane_id.root:
            return WindowId(entry.window_id)
    raise WezTermCliError(f"pane {pane_id.root} not found in wezterm cli list")


def first_spawn_args(cwd: Path, command: list[str]) -> list[str]:
    """Pure argument builder for unit tests (no subprocess)."""
    return [
        "cli",
        "spawn",
        "--new-window",
        "--workspace",
        BAND_WORKSPACE_NAME,
        "--cwd",
        str(cwd),
        "--",
        *command,
    ]


def additional_spawn_args(
    window_id: WindowId, cwd: Path, command: list[str]
) -> list[str]:
    """Pure argument builder for unit tests (no subprocess)."""
    return [
        "cli",
        "spawn",
        "--window-id",
        str(window_id.root),
        "--cwd",
        str(cwd),
        "--",
        *command,
    ]


def set_tab_title_args(pane_id: PaneId, title: str) -> list[str]:
    """Pure argument builder for unit tests (no subprocess)."""
    return [
        "cli",
        "set-tab-title",
        "--pane-id",
        str(pane_id.root),
        title,
    ]
