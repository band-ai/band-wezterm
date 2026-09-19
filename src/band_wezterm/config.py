"""Host configuration — public OAuth metadata only (never secrets)."""

from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_OAUTH_ISSUER = "https://auth.band.ai"
DEFAULT_BAND_BASE_URL = "https://api.dev.band.ai"
DEFAULT_BAND_WS_URL = "wss://api.dev.band.ai/api/v1/socket/websocket"
BAND_WORKSPACE_NAME = "band"
CONTROL_TAB_TITLE = "Control"
REFRESH_EARLY_MS = 60_000
OAUTH_SCOPES = "openid email profile offline_access"
CALLBACK_PATH = "/callback"
KEYRING_SERVICE = "band-wezterm"
KEYRING_USER_TOKENS = "userTokens"
LOCAL_STATE_DIRNAME = ".band-wezterm"
# Matches band-plugin-vsc DEFAULT_CHAT_MESSAGES_LIMIT — latest page on room enter.
CHAT_MESSAGES_LIMIT = 20


class Settings(BaseSettings):
    """Dev path: env vars. Release: packaged public client pair (dedicated client_id).

    Product ``.env`` only — live tests load ``.env.test`` into ``os.environ``
    via dotenv (see ``tests/conftest.py``), matching band-sdk-python.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    band_oauth_client_id: str = Field(default="", validation_alias="BAND_OAUTH_CLIENT_ID")
    band_oauth_issuer: str = Field(
        default=DEFAULT_OAUTH_ISSUER, validation_alias="BAND_OAUTH_ISSUER"
    )
    band_base_url: str = Field(
        default=DEFAULT_BAND_BASE_URL,
        validation_alias=AliasChoices("BAND_BASE_URL", "BAND_REST_URL"),
    )
    band_ws_url: str = Field(
        default=DEFAULT_BAND_WS_URL, validation_alias="BAND_WS_URL"
    )


def load_settings() -> Settings:
    return Settings()
