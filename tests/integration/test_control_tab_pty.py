"""Real-PTY Control tab + live platform ops via ``.env.test``.

Self-skips when ``BAND_API_KEY_USER`` is absent (CI never injects one) —
same opt-in gate as band-plugin-vsc ``liveFlow.test.ts`` and
band-sdk-python integration fixtures.
"""

from __future__ import annotations

import asyncio
import os
import sys

import pytest

from tests.live_settings import live_settings, user_api_key
from tests.paths import REPO_ROOT

pytestmark = pytest.mark.live_platform

if sys.platform.startswith("win"):
    pytest.skip("pexpect.spawn real-PTY semantics unavailable on Windows", allow_module_level=True)

pexpect = pytest.importorskip("pexpect")
pyte = pytest.importorskip("pyte")

_LIVE_KEY = user_api_key()


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


@pytest.mark.skipif(_LIVE_KEY is None, reason="BAND_API_KEY_USER not set (see .env.test)")
def test_live_room_participant_flow_with_user_api_key() -> None:
    """create_room → add_participant → @mention → remove_participant."""
    from band_wezterm.client import BandClient
    from band_wezterm.config import Settings

    settings = live_settings()
    cfg = Settings(
        band_base_url=settings.band_base_url,
        band_ws_url=settings.band_ws_url,
    )

    async def run() -> None:
        assert _LIVE_KEY is not None
        client = BandClient(api_key=_LIVE_KEY, settings=cfg)
        try:
            if settings.test_agent_id:
                agent_id = settings.test_agent_id
                agents = await client.list_my_agents()
                match = next((a for a in agents if a.id == agent_id), None)
                agent_name = match.name if match else agent_id
            else:
                agents = await client.list_my_agents()
                if not agents:
                    pytest.skip("No agents available on this account")
                agent = agents[0]
                agent_id, agent_name = agent.id, agent.name

            room = await client.create_room(title="band-wezterm-live-poc")
            await client.add_participant(room.id, agent_id)
            await client.send_message(
                room.id,
                "ping from .env.test harness",
                mention_id=agent_id,
                mention_name=agent_name,
            )
            await client.remove_participant(room.id, agent_id)
            assert room.id
        finally:
            await client.aclose()

    asyncio.run(run())


@pytest.mark.skipif(_LIVE_KEY is None, reason="BAND_API_KEY_USER not set (see .env.test)")
def test_signed_in_control_tab_renders(screen: tuple[object, object]) -> None:
    """Control tab chrome renders in a real PTY (sign-in UI when no OAuth)."""
    display, stream = screen
    env = {**os.environ, "BAND_WEZTERM_CONTROL": "1"}
    child = pexpect.spawn(
        sys.executable,
        ["-m", "band_wezterm.tui"],
        cwd=str(REPO_ROOT),
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
    finally:
        child.terminate(force=True)
