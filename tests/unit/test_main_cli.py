"""CLI entrypoint parsing and setup wiring for band."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from filelock import Timeout

from band_wezterm.__main__ import (
    COMMAND_NAME,
    SETUP_COMMAND,
    RoomSelectionError,
    _parse_args,
    _resolve_room_id,
    _run_control,
    main,
)
from band_wezterm.setup_wezterm import SetupAction, SetupConfigError, SetupResult
from band_wezterm.wezterm_cli import WezTermNotFoundError


@pytest.fixture(autouse=True)
def _not_control_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "band_wezterm.__main__.is_control_process",
        lambda: False,
    )


def test_parse_default_has_no_setup_command() -> None:
    args = _parse_args([])
    assert args.command is None
    assert args.restart is False


def test_help_uses_the_band_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exited:
        _parse_args(["--help"])
    assert exited.value.code == 0
    assert f"usage: {COMMAND_NAME}" in capsys.readouterr().out


def test_parse_restart_flag() -> None:
    args = _parse_args(["--restart"])
    assert args.command is None
    assert args.restart is True


def test_parse_setup_subcommand() -> None:
    args = _parse_args([SETUP_COMMAND])
    assert args.command == SETUP_COMMAND
    assert args.restart is False


def test_parse_room_subcommand() -> None:
    args = _parse_args(["room", "room-1"])
    assert args.room == "room-1"


def test_parse_room_without_a_reference_opens_control_picker() -> None:
    assert _parse_args(["room"]).room is None


@pytest.mark.asyncio
async def test_room_reference_resolves_an_exact_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.list_my_chats = AsyncMock(
        return_value=[MagicMock(id="room-1", title="Planning")]
    )
    client.aclose = AsyncMock()
    monkeypatch.setattr("band_wezterm.__main__.BandClient", lambda _auth: client)

    assert await _resolve_room_id("planning") == "room-1"
    client.aclose.assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_room_reference_explains_how_to_choose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = MagicMock()
    client.list_my_chats = AsyncMock(return_value=[])
    client.aclose = AsyncMock()
    monkeypatch.setattr("band_wezterm.__main__.BandClient", lambda _auth: client)

    with pytest.raises(RoomSelectionError, match="Run `band` to choose a room"):
        await _resolve_room_id("missing")


def test_main_help_is_a_discoverable_command(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["help"]) == 0
    help_text = capsys.readouterr().out
    assert "NAME_OR_ID" in help_text
    assert "choose one in Control" in help_text


def test_setup_help_mentions_active_config(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exited:
        _parse_args([SETUP_COMMAND, "-h"])
    assert exited.value.code == 0
    help_text = capsys.readouterr().out
    assert "active WezTerm config" in help_text
    assert "WEZTERM_CONFIG_FILE" in help_text
    assert "~/.wezterm.lua" in help_text
    assert "XDG" in help_text


def test_main_setup_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
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
    def _boom() -> SetupResult:
        raise WezTermNotFoundError("wezterm not found on PATH")

    monkeypatch.setattr("band_wezterm.__main__.ensure_band_plugin_config", _boom)
    assert main([SETUP_COMMAND]) == 1
    err = capsys.readouterr().err
    assert "wezterm not found on PATH" in err
    assert "brew install --cask wezterm" in err


def test_main_setup_config_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom() -> SetupResult:
        raise SetupConfigError("WezTerm config path is not a file: /tmp/.wezterm.lua")

    monkeypatch.setattr("band_wezterm.__main__.ensure_band_plugin_config", _boom)
    assert main([SETUP_COMMAND]) == 1
    err = capsys.readouterr().err
    assert "not a file" in err
    assert "/tmp/.wezterm.lua" in err


def test_main_setup_oserror(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom() -> SetupResult:
        raise OSError(13, "Permission denied", "/tmp/.wezterm.lua")

    monkeypatch.setattr("band_wezterm.__main__.ensure_band_plugin_config", _boom)
    assert main([SETUP_COMMAND]) == 1
    err = capsys.readouterr().err
    assert "Permission denied" in err


def test_run_control_uses_the_current_wezterm_pane(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr("band_wezterm.__main__._control_lock_path", lambda: tmp_path / "lock")
    monkeypatch.setenv("WEZTERM_PANE", "81")
    room_ids: list[str | None] = []
    monkeypatch.setattr(
        "band_wezterm.__main__.run_control_app",
        lambda *, initial_room_id=None: room_ids.append(initial_room_id) or 0,
    )
    assert _run_control(room_id="room-1") == 0
    assert room_ids == ["room-1"]


def test_run_control_starts_a_gui_outside_wezterm(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    started: list[tuple[Path, list[str]]] = []
    monkeypatch.delenv("WEZTERM_PANE", raising=False)
    monkeypatch.setattr("band_wezterm.__main__._control_lock_path", lambda: tmp_path / "lock")
    monkeypatch.setattr(
        "band_wezterm.__main__.start_first_window",
        lambda cwd, command: started.append((cwd, command)),
    )

    assert _run_control() == 0
    assert started == [
        (
            Path.cwd(),
            [
                "env",
                "-u",
                "NO_COLOR",
                "COLORTERM=truecolor",
                sys.executable,
                "-m",
                "band_wezterm.tui",
            ],
        )
    ]


def test_main_reports_a_concurrent_control_launch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class BusyLock:
        def __init__(self, *_: object, **__: object) -> None:
            pass

        def __enter__(self) -> None:
            raise Timeout("control launch")

        def __exit__(
            self,
            _exception_type: object,
            _exception: object,
            _traceback: object,
        ) -> bool:
            return False

    monkeypatch.setattr("band_wezterm.__main__.FileLock", BusyLock)

    assert main([]) == 1
    assert "still in progress" in capsys.readouterr().err
