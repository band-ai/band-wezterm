"""Render Control-tab SVGs for README.md.

No live WezTerm or platform needed — same mocked seams as the unit Pilot tests.

    uv run python docs/capture_screenshots.py
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from collections.abc import Awaitable, Callable
from pathlib import Path
from unittest.mock import MagicMock, create_autospec, patch

from textual.pilot import Pilot

from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.client import (
    AgentRecord,
    BandClient,
    MessageRecord,
    ParticipantRecord,
    RoomRecord,
)
from band_wezterm.config import Settings
from band_wezterm.identity import AvatarKind, HarnessId, agent_accent, parse_harness
from band_wezterm.local_state import StarredRooms
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.preferences import PreferencesStore
from band_wezterm.room_color import room_accent
from band_wezterm.tui.control_app import ControlApp
from band_wezterm.wezterm_cli import PaneId

REPO = Path(__file__).resolve().parents[1]
IMAGES = Path(__file__).resolve().parent / "images"
HOST_USER_ID = "b1c0f6f4-0f6e-4a2f-9a5e-2f9f0d2b7c11"
CLAUDE_ID = "7c2e1a90-4b3d-4f8e-9c1a-2d3e4f5a6b7c"
CODEX_ID = "a18b2c3d-e45f-4678-9abc-def012345678"
DESIGNER_ID = "0aa1bb2c-3dd4-4ee5-8ff6-99aa00bb11cc"
LAUNCH_ID = "11111111-2222-4333-8444-555555555555"
DESIGN_ID = "22222222-3333-4444-8555-666666666666"
ONCALL_ID = "33333333-4444-4555-8666-777777777777"
CLAUDE_PANE = PaneId(11)

Capture = Callable[[ControlApp, Pilot[None]], Awaitable[None]]


def _color() -> None:
    """Match a real WezTerm pane — launchers often export NO_COLOR."""
    os.environ.pop("NO_COLOR", None)
    if os.environ.get("FORCE_COLOR") == "0":
        os.environ.pop("FORCE_COLOR", None)
    os.environ.setdefault("COLORTERM", "truecolor")


def _agent(agent_id: str, name: str, harness: HarnessId) -> AgentRecord:
    return AgentRecord(
        id=agent_id,
        name=name,
        kind=AvatarKind.AGENT,
        color=agent_accent(agent_id),
        harness=parse_harness(harness),
    )


def _participant(record: AgentRecord) -> ParticipantRecord:
    return ParticipantRecord(
        id=record.id, name=record.name, kind=record.kind, color=record.color
    )


def _room(room_id: str, title: str) -> RoomRecord:
    return RoomRecord(id=room_id, title=title, color=room_accent(room_id))


def _human() -> ParticipantRecord:
    return ParticipantRecord(
        id=HOST_USER_ID,
        name="You",
        kind=AvatarKind.HUMAN,
        color=agent_accent(HOST_USER_ID),
    )


async def _settle(pilot: Pilot[None]) -> None:
    await pilot.pause()
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()


def _client() -> MagicMock:
    claude = _agent(CLAUDE_ID, "Claude", HarnessId.CLAUDE_SDK)
    codex = _agent(CODEX_ID, "Codex", HarnessId.CODEX)
    designer = _agent(DESIGNER_ID, "Designer", HarnessId.OPENCODE)
    client = create_autospec(BandClient, spec_set=True, instance=True)
    client.whoami.return_value = HOST_USER_ID
    client.list_my_agents.return_value = [claude, codex, designer]
    client.list_my_chats.return_value = [
        _room(LAUNCH_ID, "Launch"),
        _room(DESIGN_ID, "Design review"),
        _room(ONCALL_ID, "On-call"),
    ]
    client.list_participants.return_value = [
        _human(),
        _participant(claude),
        _participant(codex),
    ]
    client.list_directory.return_value = []
    client.list_messages.return_value = [
        MessageRecord(
            id="m1",
            author_name="You",
            content="@Claude summarize the launch checklist",
        ),
        MessageRecord(
            id="m2",
            author_name="Claude",
            content="Three blockers left — OAuth, Windows install, live PTY.",
        ),
        MessageRecord(
            id="m3",
            author_name="You",
            content="@Codex take Windows",
        ),
        MessageRecord(
            id="m4",
            author_name="Codex",
            content="`install.bat` is in — uv tool + `band setup`.",
        ),
    ]
    client.subscribe_realtime.return_value = lambda: None
    return client


def _app(tmp: Path, client: MagicMock) -> ControlApp:
    starred = StarredRooms(tmp / "local_state.json")
    starred.star(HOST_USER_ID, LAUNCH_ID)
    host_auth = create_autospec(HostAuth, spec_set=True, instance=True)
    host_auth.has_stored_tokens.return_value = True
    host_auth.get_access_token.return_value = "access-token"
    app = ControlApp(
        settings=Settings(),
        host_auth=host_auth,
        client=client,
        starred=starred,
        managed_agents=ManagedAgentStore(tmp / "managed_agents.json"),
        preferences=PreferencesStore(tmp / "preferences.json"),
    )
    app.agents_store.mark_running(CLAUDE_ID, CLAUDE_PANE)
    return app


async def _capture_workspace(_app: ControlApp, _pilot: Pilot[None]) -> None:
    return


async def _capture_room(app: ControlApp, pilot: Pilot[None]) -> None:
    app.action_show_rooms()
    await _settle(pilot)
    await pilot.press("enter")
    await _settle(pilot)


async def _capture_register(_app: ControlApp, pilot: Pilot[None]) -> None:
    await pilot.press("n")
    await _settle(pilot)


async def _write(name: str, capture: Capture, size: tuple[int, int]) -> Path:
    client = _client()
    with tempfile.TemporaryDirectory() as raw:
        app = _app(Path(raw), client)
        async with app.run_test(size=size) as pilot:
            await _settle(pilot)
            await capture(app, pilot)
            svg = app.export_screenshot()
    path = IMAGES / name
    path.write_text(svg, encoding="utf-8")
    return path


async def _main() -> None:
    _color()
    IMAGES.mkdir(parents=True, exist_ok=True)
    with (
        patch("band_wezterm.tui.control_app.kill_panes"),
        patch("band_wezterm.pane_identity.announce_control_human"),
    ):
        written = [
            await _write("workspace.svg", _capture_workspace, (110, 16)),
            await _write("control-room.svg", _capture_room, (110, 28)),
            await _write("register-agent.svg", _capture_register, (88, 18)),
        ]
    for path in written:
        print(path.relative_to(REPO))


if __name__ == "__main__":
    asyncio.run(_main())
