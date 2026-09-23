"""Live-platform credentials from ``.env.test`` (sibling pattern).

``tests/conftest.py`` loads dotenv once. This module only reads ``os.environ``.
API hosts are forced to ``api.dev`` (vscode ``.vscode-test.mjs`` pattern) so
stale ``platform.dev`` SPA URLs in ``.env.test`` never win.
"""

from __future__ import annotations

import os

# Keep literals here (not product Settings) so conftest can force hosts before
# ``band_wezterm`` is guaranteed importable.
LIVE_REST_URL = "https://api.dev.band.ai"
LIVE_WS_URL = "wss://api.dev.band.ai/api/v1/socket/websocket"
LIVE_SENDER_NAME = "Band WezTerm test"


def force_live_api_hosts() -> None:
    """Overwrite SPA hosts from ``.env.test`` with the real API endpoints."""
    os.environ["BAND_BASE_URL"] = LIVE_REST_URL
    os.environ["BAND_REST_URL"] = LIVE_REST_URL
    os.environ["BAND_WS_URL"] = LIVE_WS_URL


def user_api_key() -> str:
    return os.environ.get("BAND_API_KEY_USER", "").strip()


def pinned_agent_id() -> str:
    return os.environ.get("TEST_AGENT_ID", "").strip()
