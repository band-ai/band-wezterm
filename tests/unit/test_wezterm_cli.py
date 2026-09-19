"""Unit tests for wezterm_cli argument construction (correction #1)."""

from __future__ import annotations

from pathlib import Path

from band_wezterm.wezterm_cli import (
    PaneId,
    WindowId,
    additional_spawn_args,
    first_spawn_args,
    set_tab_title_args,
)


def test_first_spawn_uses_new_window_and_workspace() -> None:
    command = ["python", "-m", "band_wezterm.tui"]
    args = first_spawn_args(Path("/tmp/work"), command)
    assert args[:3] == ["cli", "spawn", "--new-window"]
    assert "--workspace" in args
    assert args[args.index("--workspace") + 1] == "band"
    assert "--window-id" not in args
    assert args[args.index("--cwd") + 1] == "/tmp/work"
    assert args[args.index("--") + 1 :] == command


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
