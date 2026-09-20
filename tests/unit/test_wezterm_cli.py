"""Unit tests for wezterm_cli argument construction (correction #1)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from band_wezterm.wezterm_cli import (
    PaneId,
    PaneInfo,
    WindowId,
    additional_spawn_args,
    first_spawn_args,
    first_start_args,
    format_focus_sequence,
    is_control_pane,
    kill_panes,
    pane_command_env,
    set_tab_title_args,
    split_pane_args,
    start_first_window,
)


def test_first_spawn_uses_new_window_without_hidden_workspace() -> None:
    """Visible Control window: omit --workspace (wezterm#3542 has no switch CLI)."""
    command = ["python", "-m", "band_wezterm.tui"]
    cwd = Path("/tmp/work")
    args = first_spawn_args(cwd, command)
    assert args[:3] == ["cli", "spawn", "--new-window"]
    assert "--workspace" not in args
    assert "--window-id" not in args
    assert args[args.index("--cwd") + 1] == str(cwd)
    assert args[args.index("--") + 1 :] == command


def test_first_start_runs_control_when_no_gui_is_available() -> None:
    command = ["python", "-m", "band_wezterm.tui"]
    cwd = Path("/tmp/work")
    assert first_start_args(cwd, command) == [
        "start",
        "--cwd",
        str(cwd),
        "--",
        *command,
    ]


def test_start_first_window_detaches_from_the_launcher(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    launched = MagicMock()
    monkeypatch.setattr("band_wezterm.wezterm_cli.wezterm_bin", lambda: "wezterm")
    monkeypatch.setattr("band_wezterm.wezterm_cli.subprocess.Popen", launched)

    start_first_window(Path("/tmp/work"), ["python", "-m", "band_wezterm.tui"])

    assert launched.call_args.args[0][:3] == ["wezterm", "start", "--cwd"]
    assert launched.call_args.kwargs["start_new_session"] is True


def test_additional_spawn_uses_window_id_only() -> None:
    command = ["sleep", "infinity"]
    args = additional_spawn_args(WindowId(99), Path("/tmp/work"), command)
    assert "--window-id" in args
    assert args[args.index("--window-id") + 1] == "99"
    assert "--workspace" not in args
    assert "--new-window" not in args
    assert args[args.index("--") + 1 :] == command


def test_set_tab_title_targets_pane() -> None:
    args = set_tab_title_args(PaneId(42), "Control")
    assert args == ["cli", "set-tab-title", "--pane-id", "42", "Control"]


def test_split_pane_builds_bottom_bridge_command() -> None:
    command = ["python", "-m", "band_wezterm.agent"]
    cwd = Path("/tmp/work")
    args = split_pane_args(PaneId(42), cwd, command, percent=20)

    assert args == [
        "cli",
        "split-pane",
        "--pane-id",
        "42",
        "--bottom",
        "--percent",
        "20",
        "--cwd",
        str(cwd),
        "--",
        *command,
    ]


@pytest.mark.parametrize("percent", [0, 100])
def test_split_pane_rejects_invalid_percent(percent: int) -> None:
    with pytest.raises(ValueError, match="between 1 and 99"):
        split_pane_args(PaneId(42), Path("/tmp/work"), ["true"], percent=percent)


def test_kill_panes_attempts_every_pane_after_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    killed: list[PaneId] = []

    def kill(pane_id: PaneId) -> None:
        killed.append(pane_id)
        if pane_id == PaneId(1):
            raise OSError("closed")

    monkeypatch.setattr("band_wezterm.wezterm_cli.kill_pane", kill)

    with pytest.raises(OSError, match="closed"):
        kill_panes((PaneId(1), PaneId(2)))

    assert killed == [PaneId(1), PaneId(2)]


def test_pane_command_env_strips_no_color() -> None:
    env = pane_command_env(
        {
            "PATH": "/bin",
            "NO_COLOR": "1",
            "FORCE_COLOR": "0",
            "TERM": "dumb",
        }
    )
    assert "NO_COLOR" not in env
    assert "FORCE_COLOR" not in env
    assert env["COLORTERM"] == "truecolor"
    assert env["TERM"] == "xterm-256color"


def test_is_control_pane_matches_tab_title() -> None:
    assert is_control_pane(
        PaneInfo(window_id=1, pane_id=2, tab_title="Control", title="python")
    )
    assert not is_control_pane(
        PaneInfo(window_id=1, pane_id=3, tab_title="", title="zsh")
    )


def test_format_focus_sequence_is_osc_uservar() -> None:
    sequence = format_focus_sequence()
    assert sequence.startswith("\033]1337;SetUserVar=band.focus=")
    assert sequence.endswith("\007")
