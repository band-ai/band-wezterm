"""wezterm cli wrapper — first-spawn vs window-id rule (correction #1)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError

DEFAULT_BRIDGE_PANE_PERCENT: Final = 20


class SplitDirection(StrEnum):
    BOTTOM = "bottom"
    TOP = "top"


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
    tab_title: str | None = None
    cwd: str | None = None
    size: dict[str, object] | None = None


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


def wezterm_bin() -> str:
    path = shutil.which("wezterm")
    if path is None:
        raise WezTermNotFoundError("wezterm not found on PATH")
    return path


def _run(args: list[str], *, env: Mapping[str, str] | None = None) -> str:
    completed = subprocess.run(
        [wezterm_bin(), *args],
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
    """Open a new visible window with the Band surface as the first pane.

    The first surface uses ``--new-window`` (not ``--window-id``).
    We intentionally omit ``--workspace``: WezTerm has no CLI to switch the GUI
    to a differently named workspace, so a ``band`` workspace stays hidden
    (wezterm#3542). Window title is set by the host instead.
    """
    stdout = _run(
        [
            "cli",
            "spawn",
            "--new-window",
            "--cwd",
            str(cwd),
            "--",
            *command,
        ]
    )
    pane_id = PaneId(int(stdout.splitlines()[-1].strip()))
    window_id = _window_id_for_pane(pane_id)
    return SpawnResult(window_id=window_id, pane_id=pane_id)


def start_first_window(cwd: Path, command: list[str]) -> None:
    """Start a GUI and run a Band surface when no GUI is available for ``cli``."""
    subprocess.Popen(
        [wezterm_bin(), *first_start_args(cwd, command)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def spawn_additional_tab(
    window_id: WindowId, cwd: Path, command: list[str]
) -> PaneId:
    """Spawn a subsequent tab into an existing Band window."""
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


def split_pane(
    pane_id: PaneId,
    cwd: Path,
    command: list[str],
    *,
    percent: int = DEFAULT_BRIDGE_PANE_PERCENT,
    direction: SplitDirection = SplitDirection.BOTTOM,
) -> PaneId:
    """Split ``pane_id`` and run ``command`` in the new pane."""
    stdout = _run(
        split_pane_args(
            pane_id, cwd, command, percent=percent, direction=direction
        )
    )
    return PaneId(int(stdout.splitlines()[-1].strip()))


def kill_pane(pane_id: PaneId) -> None:
    _run(["cli", "kill-pane", "--pane-id", str(pane_id.root)])


def kill_panes(pane_ids: Iterable[PaneId]) -> None:
    """Best-effort teardown for panes that share one lifecycle."""
    failures: list[WezTermCliError | OSError] = []
    for pane_id in pane_ids:
        try:
            kill_pane(pane_id)
        except (WezTermCliError, OSError) as error:
            failures.append(error)
    if failures:
        raise failures[0]


def activate_pane(pane_id: PaneId) -> None:
    _run(["cli", "activate-pane", "--pane-id", str(pane_id.root)])


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


def set_window_title(pane_id: PaneId, title: str) -> None:
    _run(
        [
            "cli",
            "set-window-title",
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
    """Resolve the window that owns one Band surface pane."""
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
        "--cwd",
        str(cwd),
        "--",
        *command,
    ]


def first_start_args(cwd: Path, command: list[str]) -> list[str]:
    """Pure GUI-start argument builder for launcher recovery tests."""
    return ["start", "--cwd", str(cwd), "--", *command]


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


def split_pane_args(
    pane_id: PaneId,
    cwd: Path,
    command: list[str],
    *,
    percent: int = DEFAULT_BRIDGE_PANE_PERCENT,
    direction: SplitDirection = SplitDirection.BOTTOM,
) -> list[str]:
    """Pure split command builder for unit tests."""
    if not 1 <= percent <= 99:
        raise ValueError("split pane percent must be between 1 and 99")
    return [
        "cli",
        "split-pane",
        "--pane-id",
        str(pane_id.root),
        f"--{direction.value}",
        "--percent",
        str(percent),
        "--cwd",
        str(cwd),
        "--",
        *command,
    ]
