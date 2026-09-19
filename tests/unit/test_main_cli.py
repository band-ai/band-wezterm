"""CLI entrypoint parsing for band-wezterm."""

from __future__ import annotations

from band_wezterm.__main__ import SETUP_COMMAND, _parse_args


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
