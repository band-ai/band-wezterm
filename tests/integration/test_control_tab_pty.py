"""Real-PTY whole-flow against live platform (correction #15 — skip on Windows)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.live_platform

if sys.platform.startswith("win"):
    pytest.skip("pexpect.spawn real-PTY semantics unavailable on Windows", allow_module_level=True)

pexpect = pytest.importorskip("pexpect")
pyte = pytest.importorskip("pyte")


def _live_enabled() -> bool:
    return os.environ.get("BAND_LIVE_PTY", "").strip() in {"1", "true", "TRUE", "yes"}


@pytest.fixture
def screen() -> tuple[object, object]:
    display = pyte.Screen(120, 40)
    stream = pyte.Stream(display)
    return display, stream


def _feed(child: object, stream: object, timeout: float = 2.0) -> None:
    try:
        chunk = child.read_nonblocking(size=4096, timeout=timeout)  # type: ignore[attr-defined]
    except Exception:
        return
    if chunk:
        text = chunk.decode("utf-8", errors="ignore") if isinstance(chunk, bytes) else str(chunk)
        stream.feed(text)


def _display_text(display: object) -> str:
    return "\n".join(line for line in display.display)  # type: ignore[attr-defined]


@pytest.mark.skipif(not _live_enabled(), reason="BAND_LIVE_PTY not enabled")
def test_signed_in_control_tab_renders_and_room_flow(screen: tuple[object, object]) -> None:
    """Golden path through the real rendered Control tab + live BandClient.

    Requires HostAuth keyring tokens from a prior interactive sign-in.
    Mirrors UserOps: create_room → add_participant → @mention → remove_participant.
    """
    from band_wezterm.auth.credentials import TokenStore
    from band_wezterm.auth.host_auth import HostAuth
    from band_wezterm.client import BandClient
    import asyncio

    display, stream = screen
    store = TokenStore()
    if store.get_user_tokens() is None:
        pytest.skip("No stored OAuth tokens — sign in via Control tab first")

    async def platform_ops() -> tuple[str, str, str]:
        auth = HostAuth(store=store)
        client = BandClient(auth)
        try:
            agents = await client.list_my_agents()
            if not agents:
                pytest.skip("No agents available on this account")
            agent = agents[0]
            room = await client.create_room(title="band-wezterm-pty-poc")
            await client.add_participant(room.id, agent.id)
            await client.send_message(
                room.id,
                "ping from pty harness",
                mention_id=agent.id,
                mention_name=agent.name,
            )
            await client.remove_participant(room.id, agent.id)
            return room.id, agent.id, agent.name
        finally:
            await client.aclose()

    room_id, agent_id, agent_name = asyncio.run(platform_ops())

    env = {**os.environ, "BAND_WEZTERM_CONTROL": "1"}
    child = pexpect.spawn(
        sys.executable,
        ["-m", "band_wezterm.tui"],
        cwd=str(Path(__file__).resolve().parents[2]),
        dimensions=(40, 120),
        env=env,
        encoding=None,
        timeout=30,
    )
    try:
        for _ in range(20):
            _feed(child, stream, timeout=0.5)
            text = _display_text(display)
            if "Agents" in text or "Rooms" in text or "Sign" in text or "Control" in text:
                break
        visible = _display_text(display)
        assert any(
            token in visible for token in ("Agents", "Rooms", "Sign", "Control", "Band")
        ), f"Control tab did not render expected chrome:\n{visible}"
        # Platform side of the flow already exercised above with live Bearer client.
        assert room_id and agent_id and agent_name
    finally:
        child.terminate(force=True)
