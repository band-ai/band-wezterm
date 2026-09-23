"""Shared Textual test synchronization helpers."""

from __future__ import annotations

from textual.pilot import Pilot


async def settle(pilot: Pilot[None]) -> None:
    """Wait for background workers and their resulting repaint."""
    await pilot.pause()
    await pilot.app.workers.wait_for_complete()
    await pilot.pause()
