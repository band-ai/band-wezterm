"""One refresh policy for platform catalogs and local detached workers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from textual.screen import Screen

# Band realtime currently exposes room messages and roster events. Catalogs and
# local supervisor state have no push topic, so they use bounded polling.
PLATFORM_CATALOG_POLL_SECONDS: Final = 10.0
LOCAL_RUNTIME_POLL_SECONDS: Final = 2.0


def install_catalog_refresh(screen: Screen[object], refresh: Callable[[], None]) -> None:
    """Poll a REST catalog only while its owning screen is visible."""
    screen.set_interval(
        PLATFORM_CATALOG_POLL_SECONDS,
        lambda: refresh() if screen.is_current else None,
    )
