"""CLI entrypoint parsing and setup wiring for band-wezterm."""

from __future__ import annotations

from pathlib import Path

import pytest

from band_wezterm.__main__ import SETUP_COMMAND, _parse_args, main
from band_wezterm.setup_wezterm import SetupAction, SetupResult
from band_wezterm.wezterm_cli import WezTermNotFoundError


def test_parse_default_has_no_setup_command() -> None:
    args = _parse_args([])
    assert args.command is None
    assert args.restart is False


def test_parse_restart_flag() -> None:
    args = _parse_args(["--restart"])
    assert args.command is None
    assert args.restart is True


def test_parse_setup_subcommand() -> None:
    args = _parse_args([SETUP_COMMAND])
    assert args.command == SETUP_COMMAND
    assert args.restart is False


def test_main_setup_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "band_wezterm.__main__.is_control_process",
        lambda: False,
    )
    monkeypatch.setattr(
        "band_wezterm.__main__.ensure_band_plugin_config",
        lambda: SetupResult(path=tmp_path / ".wezterm.lua", action=SetupAction.CREATED),
    )
    assert main([SETUP_COMMAND]) == 0
    out = capsys.readouterr().out
    assert "Created" in out
    assert str(tmp_path / ".wezterm.lua") in out


def test_main_setup_missing_wezterm(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "band_wezterm.__main__.is_control_process",
        lambda: False,
    )

    def _boom() -> SetupResult:
        raise WezTermNotFoundError("wezterm not found on PATH")

    monkeypatch.setattr("band_wezterm.__main__.ensure_band_plugin_config", _boom)
    assert main([SETUP_COMMAND]) == 1
    err = capsys.readouterr().err
    assert "wezterm not found on PATH" in err
    assert "brew install --cask wezterm" in err
