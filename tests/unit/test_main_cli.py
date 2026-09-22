"""CLI entrypoint parsing and setup wiring for band."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from band_wezterm.__main__ import (
    RoomSelectionError,
    _resolve_room_id,
    _run_agent_action,
    _run_agents,
    _run_rooms,
    _run_status,
    _run_view,
    main,
)
from band_wezterm.cli import AgentAction, Command
from band_wezterm.setup_wezterm import SetupAction, SetupConfigError, SetupResult
from band_wezterm.wezterm_cli import WezTermNotFoundError


@pytest.fixture(autouse=True)
def _not_control_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "band_wezterm.__main__.is_control_process",
        lambda: False,
    )


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

    with pytest.raises(RoomSelectionError, match="Run `band room` to choose a room"):
        await _resolve_room_id("missing")


@pytest.mark.asyncio
async def test_rooms_lists_titles_and_ids(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client = MagicMock()
    client.list_my_chats = AsyncMock(
        return_value=[
            MagicMock(id="room-1", title="Planning"),
            MagicMock(id="room-2", title="Delivery"),
        ]
    )
    client.aclose = AsyncMock()
    monkeypatch.setattr("band_wezterm.__main__.BandClient", lambda _auth: client)

    assert await _run_rooms() == 0
    assert capsys.readouterr().out.splitlines() == [
        "Planning\troom-1",
        "Delivery\troom-2",
    ]


@pytest.mark.asyncio
async def test_status_separates_rooms_and_agents(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    supervisor = MagicMock()
    supervisor.list_workers = AsyncMock(
        return_value=[
            SimpleNamespace(
                name="Architect",
                agent_id="agent-1",
                state=SimpleNamespace(value="running"),
                pid=42,
            )
        ]
    )
    monkeypatch.setattr(
        "band_wezterm.__main__._list_rooms",
        AsyncMock(return_value=[SimpleNamespace(title="Planning", id="room-1")]),
    )
    monkeypatch.setattr(
        "band_wezterm.__main__._current_supervisor", AsyncMock(return_value=supervisor)
    )
    monkeypatch.setattr(
        "band_wezterm.__main__._list_agents",
        AsyncMock(return_value=[SimpleNamespace(name="Architect", id="agent-1")]),
    )

    assert await _run_status() == 0
    assert capsys.readouterr().out.splitlines() == [
        "Rooms",
        "Planning\troom-1\tband room room-1",
        "",
        "Agents",
        "Architect\tagent-1\trunning\tband agent stop agent-1",
    ]


def test_bare_band_shows_the_resource_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["help"]) == 0
    help_text = capsys.readouterr().out
    assert "agent" in help_text
    assert "room" in help_text


@pytest.mark.asyncio
async def test_agents_list_includes_the_next_lifecycle_command(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    supervisor = MagicMock()
    supervisor.list_workers = AsyncMock(return_value=[])
    monkeypatch.setattr(
        "band_wezterm.__main__._current_supervisor", AsyncMock(return_value=supervisor)
    )
    monkeypatch.setattr(
        "band_wezterm.__main__._list_agents",
        AsyncMock(return_value=[SimpleNamespace(name="Architect", id="agent-1")]),
    )

    assert await _run_agents() == 0
    assert capsys.readouterr().out.splitlines() == [
        "Agents",
        "Architect\tagent-1\tstopped\tband agent start agent-1",
    ]


@pytest.mark.asyncio
async def test_agent_start_reports_the_detached_worker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    supervisor = MagicMock()
    supervisor.start = AsyncMock(
        return_value=SimpleNamespace(
            name="Architect",
            agent_id="agent-1",
            state=SimpleNamespace(value="starting"),
            pid=42,
        )
    )
    monkeypatch.setattr(
        "band_wezterm.__main__._current_supervisor", AsyncMock(return_value=supervisor)
    )

    assert await _run_agent_action(AgentAction.START, "agent-1") == 0
    supervisor.start.assert_awaited_once_with("agent-1", cwd=Path.cwd())
    assert capsys.readouterr().out == "Architect\tagent-1\tstarting\tpid 42\n"


def test_setup_help_mentions_active_config(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main([Command.SETUP.value, "--help"]) == 0
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
    assert main([Command.SETUP.value]) == 0
    out = capsys.readouterr().out
    assert "Created" in out
    assert str(tmp_path / ".wezterm.lua") in out


def test_main_setup_missing_wezterm(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom() -> SetupResult:
        raise WezTermNotFoundError("wezterm not found on PATH")

    monkeypatch.setattr("band_wezterm.__main__.ensure_band_plugin_config", _boom)
    assert main([Command.SETUP.value]) == 1
    err = capsys.readouterr().err
    assert "wezterm not found on PATH" in err
    assert "brew install --cask wezterm" in err


def test_main_setup_config_error(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom() -> SetupResult:
        raise SetupConfigError("WezTerm config path is not a file: /tmp/.wezterm.lua")

    monkeypatch.setattr("band_wezterm.__main__.ensure_band_plugin_config", _boom)
    assert main([Command.SETUP.value]) == 1
    err = capsys.readouterr().err
    assert "not a file" in err
    assert "/tmp/.wezterm.lua" in err


def test_main_setup_oserror(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def _boom() -> SetupResult:
        raise OSError(13, "Permission denied", "/tmp/.wezterm.lua")

    monkeypatch.setattr("band_wezterm.__main__.ensure_band_plugin_config", _boom)
    assert main([Command.SETUP.value]) == 1
    err = capsys.readouterr().err
    assert "Permission denied" in err


def test_run_view_uses_the_current_wezterm_pane(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEZTERM_PANE", "81")
    room_ids: list[str | None] = []
    monkeypatch.setattr(
        "band_wezterm.__main__.run_control_app",
        lambda *, initial_room_id=None: room_ids.append(initial_room_id) or 0,
    )
    assert _run_view(room_id="room-1") == 0
    assert room_ids == ["room-1"]


def test_run_view_starts_a_gui_outside_wezterm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[tuple[Path, list[str]]] = []
    monkeypatch.delenv("WEZTERM_PANE", raising=False)
    monkeypatch.setattr(
        "band_wezterm.__main__.start_first_window",
        lambda cwd, command: started.append((cwd, command)),
    )

    assert _run_view() == 0
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
