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
    _run_agents,
    _run_configure_agent,
    _run_create_agent,
    _run_rooms,
    _run_start_agent,
    _run_status,
    _run_stop_agent,
    _run_view,
    main,
)
from band_wezterm.cli import Command
from band_wezterm.setup_wezterm import SetupAction, SetupConfigError, SetupResult
from band_wezterm.tui.control_app import AppScreen, InitialAgentAction
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
    output = capsys.readouterr().out
    assert all(value in output for value in ("Rooms", "Planning", "Delivery", "room-1"))


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

    assert await _run_status(False, False) == 0
    output = capsys.readouterr().out
    assert all(
        value in output
        for value in ("Rooms", "Planning", "Agents", "Architect", "running")
    )


@pytest.mark.asyncio
async def test_status_can_select_only_rooms(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        "band_wezterm.__main__._list_rooms",
        AsyncMock(return_value=[SimpleNamespace(title="Planning", id="room-1")]),
    )
    agents = AsyncMock()
    monkeypatch.setattr("band_wezterm.__main__._run_agents", agents)

    assert await _run_status(True, False) == 0
    assert "Rooms" in capsys.readouterr().out
    agents.assert_not_awaited()


@pytest.mark.asyncio
async def test_stop_all_delegates_to_the_supervisor(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    operations = MagicMock()
    operations.stop_all = AsyncMock()
    client = MagicMock()
    client.aclose = AsyncMock()
    monkeypatch.setattr(
        "band_wezterm.__main__._current_agent_operations",
        AsyncMock(return_value=(operations, client)),
    )

    assert await _run_stop_agent(None, True) == 0
    operations.stop_all.assert_awaited_once()
    client.aclose.assert_awaited_once()
    assert capsys.readouterr().out == "Stopping all detached agents.\n"


def test_bare_band_shows_the_resource_commands(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert main(["help"]) == 0
    help_text = capsys.readouterr().out
    assert "agent" in help_text
    assert "room" in help_text


def test_agent_create_opens_the_registration_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[dict[str, object]] = []
    monkeypatch.setattr(
        "band_wezterm.__main__._run_view",
        lambda **kwargs: opened.append(kwargs) or 0,
    )

    assert _run_create_agent() == 0
    assert opened == [
        {
            "screen": AppScreen.AGENTS,
            "agent_action": InitialAgentAction.CREATE,
        }
    ]


def test_agent_create_command_routes_to_the_registration_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    create = MagicMock(return_value=0)
    monkeypatch.setattr("band_wezterm.__main__._run_create_agent", create)

    assert main([Command.AGENT.value, Command.CREATE.value]) == 0
    create.assert_called_once_with()


def test_agent_configure_resolves_before_opening_its_flow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[dict[str, object]] = []
    monkeypatch.setattr(
        "band_wezterm.__main__._resolve_agent",
        AsyncMock(return_value=SimpleNamespace(id="agent-1", name="Architect")),
    )
    monkeypatch.setattr(
        "band_wezterm.__main__._run_view",
        lambda **kwargs: opened.append(kwargs) or 0,
    )

    assert _run_configure_agent("Architect") == 0
    assert opened == [
        {
            "screen": AppScreen.AGENTS,
            "agent_action": InitialAgentAction.CONFIGURE,
            "agent_id": "agent-1",
        }
    ]


def test_agent_configure_command_routes_the_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure = MagicMock(return_value=0)
    monkeypatch.setattr("band_wezterm.__main__._run_configure_agent", configure)

    assert main([Command.AGENT.value, Command.CONFIGURE.value, "Architect"]) == 0
    configure.assert_called_once_with("Architect")


def test_room_command_starts_the_textual_view_outside_cyclopts_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("WEZTERM_PANE", "81")
    opened: list[str | None] = []
    monkeypatch.setattr(
        "band_wezterm.__main__.run_control_app",
        lambda *, initial_room_id=None, initial_screen=None: (
            opened.append(initial_room_id) or 0
        ),
    )

    assert main(["room"]) == 0
    assert opened == [None]


@pytest.mark.asyncio
async def test_agents_list_renders_compact_state_without_an_action_column(
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
    output = capsys.readouterr().out
    assert all(
        value in output
        for value in (
            "Agents",
            "Architect",
            "stopped",
        )
    )
    assert "Action" not in output


@pytest.mark.asyncio
async def test_agent_start_reports_the_detached_worker(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    operations = MagicMock()
    operations.start = AsyncMock(
        return_value=SimpleNamespace(
            name="Architect",
            agent_id="agent-1",
            state=SimpleNamespace(value="starting"),
            pid=42,
        )
    )
    client = MagicMock()
    client.aclose = AsyncMock()
    monkeypatch.setattr(
        "band_wezterm.__main__._current_agent_operations",
        AsyncMock(return_value=(operations, client)),
    )
    monkeypatch.setattr(
        "band_wezterm.__main__._resolve_agent",
        AsyncMock(return_value=SimpleNamespace(id="agent-1", name="Architect")),
    )

    assert await _run_start_agent("agent-1") == 0
    operations.start.assert_awaited_once_with("agent-1", cwd=Path.cwd())
    client.aclose.assert_awaited_once()
    output = capsys.readouterr().out
    assert all(value in output for value in ("Agents", "Architect", "starting"))
    assert "Action" not in output


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
        lambda *, initial_room_id=None, initial_screen=None: (
            room_ids.append(initial_room_id) or 0
        ),
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
