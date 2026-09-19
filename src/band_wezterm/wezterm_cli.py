"""wezterm cli wrapper — first-spawn vs window-id rule (correction #1)."""

from __future__ import annotations

import base64
import contextlib
import json
import os
import shutil
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, RootModel, ValidationError

from band_wezterm.config import BAND_WORKSPACE_NAME, CONTROL_TAB_TITLE

# Short-lived pane that emits ``band.focus`` so Lua can SwitchToWorkspace.
_FOCUS_RELAY_SLEEP_SECONDS = "0.05"
# Inline OSC framing (same bytes as ``band_wezterm.osc``) — avoids a circular
# import with osc.py, which depends on this module for PaneId/send_text.
_OSC_PREFIX: Final = "\033]1337;SetUserVar="
_OSC_SUFFIX: Final = "\007"
_FOCUS_USER_VAR: Final = "band.focus"
_FOCUS_PAYLOAD: Final = "1"


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
    """Open a new visible window with the Control tab as the first pane.

    Correction #1: first Control uses ``--new-window`` (not ``--window-id``).
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


def spawn_additional_tab(
    window_id: WindowId, cwd: Path, command: list[str]
) -> PaneId:
    """Spawn a subsequent tab into an existing Control window (correction #1)."""
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
    """Resolve a pane's window — the Control tab uses it to find its own."""
    return _window_id_for_pane(pane_id)


def _window_id_for_pane(pane_id: PaneId) -> WindowId:
    for entry in list_panes():
        if entry.pane_id == pane_id.root:
            return WindowId(entry.window_id)
    raise WezTermCliError(f"pane {pane_id.root} not found in wezterm cli list")


def is_control_pane(entry: PaneInfo) -> bool:
    if entry.tab_title == CONTROL_TAB_TITLE:
        return True
    title = entry.title or ""
    return "band_wezterm.tui" in title or title.endswith("band_wezterm")


def find_control_pane() -> PaneInfo | None:
    """Return the running Control pane, if any."""
    controls = [entry for entry in list_panes() if is_control_pane(entry)]
    if not controls:
        return None
    # Prefer a visible (non-legacy-workspace) Control when both exist.
    for entry in controls:
        if entry.workspace != BAND_WORKSPACE_NAME:
            return entry
    return controls[0]


def panes_in_window(window_id: WindowId) -> list[PaneInfo]:
    return [entry for entry in list_panes() if entry.window_id == window_id.root]


def kill_window(window_id: WindowId) -> None:
    """Kill every pane in ``window_id`` (best-effort)."""
    for entry in panes_in_window(window_id):
        try:
            kill_pane(PaneId(entry.pane_id))
        except WezTermCliError:
            continue


def _pane_dpi(entry: PaneInfo) -> int:
    if not entry.size:
        return 0
    dpi = entry.size.get("dpi", 0)
    return int(dpi) if isinstance(dpi, (int, float)) else 0


def find_focus_relay_pane() -> PaneInfo | None:
    """A rendered pane outside the legacy ``band`` workspace, for OSC focus."""
    candidates = [
        entry
        for entry in list_panes()
        if entry.workspace != BAND_WORKSPACE_NAME and _pane_dpi(entry) > 0
    ]
    return candidates[0] if candidates else None


def format_focus_sequence() -> str:
    """OSC 1337 that the Band WezTerm plugin handles as SwitchToWorkspace + focus."""
    encoded = base64.b64encode(_FOCUS_PAYLOAD.encode("utf-8")).decode("ascii")
    return f"{_OSC_PREFIX}{_FOCUS_USER_VAR}={encoded}{_OSC_SUFFIX}"


def request_workspace_focus(*, control_pane: PaneId) -> None:
    """Ask the GUI to show Control — workspace switch (Lua) + activate + raise.

    Legacy Control panes in the ``band`` workspace are invisible until the GUI
    switches workspaces. Emit ``band.focus`` from a short-lived pane in a
    *visible* window (OSC must come from pane output, not ``send-text`` input).
    """
    control = next(
        (entry for entry in list_panes() if entry.pane_id == control_pane.root),
        None,
    )
    needs_workspace_switch = (
        control is not None and control.workspace == BAND_WORKSPACE_NAME
    )
    if needs_workspace_switch:
        relay = find_focus_relay_pane()
        if relay is not None:
            # Pass OSC via env so shell quoting cannot corrupt the escape bytes.
            with contextlib.suppress(WezTermCliError):
                _run(
                    [
                        "cli",
                        "spawn",
                        "--window-id",
                        str(relay.window_id),
                        "--",
                        "bash",
                        "-lc",
                        f'printf %s "$BAND_FOCUS_OSC"; sleep {_FOCUS_RELAY_SLEEP_SECONDS}',
                    ],
                    env={**os.environ, "BAND_FOCUS_OSC": format_focus_sequence()},
                )
    with contextlib.suppress(WezTermCliError):
        activate_pane(control_pane)
    raise_gui()


def raise_gui() -> None:
    """Bring the WezTerm application to the foreground (best-effort)."""
    if sys.platform == "darwin":
        subprocess.run(
            ["osascript", "-e", 'tell application "WezTerm" to activate'],
            check=False,
            capture_output=True,
            text=True,
        )


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
