"""Live-platform settings from ``.env.test`` (sibling pattern).

``load_dotenv`` is the single load path: skip markers and pydantic settings
both read ``os.environ``. ``override=False`` keeps explicitly exported vars
ahead of the file — same winner as pydantic's env-over-env_file priority.

Credentials come from ``.env.test``. REST/WS hosts default to the verified
API hosts (``api.dev.band.ai``) — ``.env.test``'s ``BAND_*_URL`` copies are
often the SPA host ``platform.dev.band.ai``, which returns HTML for
``/api/v1/*`` (same stale-host finding as band-plugin-vsc ``.vscode-test.mjs``).
"""

from __future__ import annotations

from urllib.parse import urlparse

from dotenv import load_dotenv
from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from tests.paths import ENV_TEST_FILE

load_dotenv(ENV_TEST_FILE, override=False)

DEFAULT_LIVE_REST_URL = "https://api.dev.band.ai"
DEFAULT_LIVE_WS_URL = "wss://api.dev.band.ai/api/v1/socket/websocket"
_SPA_API_HOSTS = frozenset({"platform.dev.band.ai"})
_API_HOST_FOR_SPA = "api.dev.band.ai"


def _rewrite_spa_host(url: str, *, websocket: bool = False) -> str:
    parsed = urlparse(url)
    if parsed.hostname not in _SPA_API_HOSTS:
        return url
    scheme = "wss" if websocket else "https"
    path = parsed.path or ("/api/v1/socket/websocket" if websocket else "")
    return f"{scheme}://{_API_HOST_FOR_SPA}{path}"


class LiveSettings(BaseSettings):
    """Credentials + URLs for opt-in live platform tests."""

    model_config = SettingsConfigDict(
        env_ignore_empty=True,
        extra="ignore",
        case_sensitive=False,
    )

    band_api_key_user: str = ""
    band_api_key: str = ""
    test_agent_id: str = ""
    band_base_url: str = Field(
        default=DEFAULT_LIVE_REST_URL,
        validation_alias=AliasChoices("BAND_BASE_URL", "BAND_REST_URL"),
    )
    band_ws_url: str = Field(
        default=DEFAULT_LIVE_WS_URL,
        validation_alias="BAND_WS_URL",
    )

    @model_validator(mode="after")
    def rewrite_stale_spa_hosts(self) -> LiveSettings:
        object.__setattr__(
            self, "band_base_url", _rewrite_spa_host(self.band_base_url)
        )
        object.__setattr__(
            self,
            "band_ws_url",
            _rewrite_spa_host(self.band_ws_url, websocket=True),
        )
        return self


def live_settings() -> LiveSettings:
    return LiveSettings()


def user_api_key() -> str | None:
    return live_settings().band_api_key_user or None
