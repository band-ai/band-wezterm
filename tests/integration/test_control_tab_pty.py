"""Real-PTY Control tab + live platform ops via ``.env.test``.

Live API tests self-skip when ``BAND_API_KEY_USER`` is absent — same opt-in
gate as band-plugin-vsc ``liveFlow.test.ts``.
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx
import pytest

from band_wezterm.client import BandClient
from band_wezterm.config import load_settings
from tests.live_settings import pinned_agent_id, user_api_key
from tests.paths import REPO_ROOT

pytestmark = pytest.mark.live_platform

if sys.platform.startswith("win"):
    pytest.skip("pexpect.spawn real-PTY semantics unavailable on Windows", allow_module_level=True)

pexpect = pytest.importorskip("pexpect")
pyte = pytest.importorskip("pyte")


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


def test_live_room_participant_flow_with_user_api_key() -> None:
    """create_room → add_participant → @mention → remove_participant."""
    api_key = user_api_key()
    if not api_key:
        pytest.skip("BAND_API_KEY_USER not set (see .env.test)")

    async def run() -> None:
        client = BandClient.from_user_api_key(api_key, load_settings())
        try:
            pinned = pinned_agent_id()
            if pinned:
                agent_id, agent_name = pinned, pinned
            else:
                try:
                    agents = await client.list_my_agents()
                except httpx.HTTPError as exc:
                    pytest.skip(f"live platform unreachable: {exc}")
                if not agents:
                    pytest.skip("No agents available on this account")
                agent = agents[0]
                agent_id, agent_name = agent.id, agent.name

            try:
                room = await client.create_room(title="band-wezterm-live-poc")
                await client.add_participant(room.id, agent_id)
                await client.send_message(
                    room.id,
                    "ping from .env.test harness",
                    mention_id=agent_id,
                    mention_name=agent_name,
                )
                await client.remove_participant(room.id, agent_id)
            except httpx.HTTPError as exc:
                pytest.skip(f"live platform unreachable: {exc}")
            assert room.id
        finally:
            await client.aclose()

    asyncio.run(run())


def test_control_tab_chrome_renders(screen: tuple[object, object]) -> None:
    """Control tab chrome renders in a real PTY (unsigned / sign-in UI)."""
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
