"""Host configuration — public OAuth metadata only (never secrets)."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Final, NamedTuple

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_OAUTH_ISSUER = "https://auth.band.ai"
# Public PKCE client shared with band-plugin-vsc (repo var BAND_OAUTH_CLIENT_ID).
DEFAULT_OAUTH_CLIENT_ID = "8b331314-a09c-485e-99dd-f4d26c7b39c7"
DEFAULT_BAND_BASE_URL = "https://app.band.ai"
DEFAULT_BAND_WS_URL = "wss://app.band.ai/api/v1/socket/websocket"
DEVELOPMENT_BAND_BASE_URL = "https://api.dev.band.ai"
DEVELOPMENT_BAND_WS_URL = "wss://api.dev.band.ai/api/v1/socket/websocket"
CONTROL_TAB_TITLE = "Band"
WINDOW_TITLE = "Band"
REFRESH_EARLY_MS = 60_000
OAUTH_SCOPES = "openid email profile offline_access"
CALLBACK_PATH = "/callback"
KEYRING_SERVICE = "band-wezterm"
KEYRING_USER_TOKENS = "userTokens"
# Mirrors band-plugin-vsc `band.managedAgentApiKey.${id}` (keyring username suffix).
KEYRING_MANAGED_AGENT_KEY_PREFIX = "managedAgentApiKey."
LOCAL_STATE_DIRNAME = ".band-wezterm"
# Matches band-plugin-vsc DEFAULT_CHAT_MESSAGES_LIMIT — latest page on room enter.
CHAT_MESSAGES_LIMIT = 20
# Child-pane env / CLI — never OSC.
AGENT_API_KEY_ENV = "BAND_AGENT_API_KEY"
AGENT_ID_ENV = "BAND_AGENT_ID"
AGENT_HARNESS_ENV = "BAND_AGENT_HARNESS"
AGENT_NAME_ENV = "BAND_AGENT_NAME"
AGENT_PERSONA_FILE_ENV = "BAND_AGENT_PERSONA_FILE"
AGENT_MODEL_ENV = "BAND_AGENT_MODEL"
AGENT_REASONING_ENV = "BAND_AGENT_REASONING"


class BandDeployment(StrEnum):
    """Known Band API deployments."""

    PRODUCTION = "production"
    DEVELOPMENT = "development"


class DeploymentEndpoints(NamedTuple):
    """OAuth issuer, REST API, and WebSocket endpoint for one deployment."""

    oauth_issuer: str
    base_url: str
    ws_url: str


DEPLOYMENT_ENDPOINTS: Final = {
    BandDeployment.PRODUCTION: DeploymentEndpoints(
        DEFAULT_OAUTH_ISSUER, DEFAULT_BAND_BASE_URL, DEFAULT_BAND_WS_URL
    ),
    BandDeployment.DEVELOPMENT: DeploymentEndpoints(
        DEFAULT_OAUTH_ISSUER, DEVELOPMENT_BAND_BASE_URL, DEVELOPMENT_BAND_WS_URL
    ),
}


class Settings(BaseSettings):
    """Public OAuth defaults match Band for VS Code / Jam; env vars override.

    Product ``.env`` only — live tests load ``.env.test`` into ``os.environ``
    via dotenv (see ``tests/conftest.py``), matching band-sdk-python.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    band_deployment: BandDeployment = Field(
        default=BandDeployment.PRODUCTION, validation_alias="BAND_DEPLOYMENT"
    )
    band_oauth_client_id: str = Field(
        default=DEFAULT_OAUTH_CLIENT_ID, validation_alias="BAND_OAUTH_CLIENT_ID"
    )
    band_oauth_issuer: str = Field(default="", validation_alias="BAND_OAUTH_ISSUER")
    band_base_url: str = Field(
        default="",
        validation_alias=AliasChoices("BAND_BASE_URL", "BAND_REST_URL"),
    )
    band_ws_url: str = Field(default="", validation_alias="BAND_WS_URL")

    @field_validator("band_deployment", mode="before")
    @classmethod
    def _deployment(cls, value: object) -> object:
        if isinstance(value, str) and value.strip().lower() == "dev":
            return BandDeployment.DEVELOPMENT
        return value

    @model_validator(mode="after")
    def _resolve_deployment_endpoints(self) -> Settings:
        endpoints = DEPLOYMENT_ENDPOINTS[self.band_deployment]
        self.band_oauth_issuer = self.band_oauth_issuer or endpoints.oauth_issuer
        self.band_base_url = self.band_base_url or endpoints.base_url
        self.band_ws_url = self.band_ws_url or endpoints.ws_url
        return self

    @property
    def keyring_service(self) -> str:
        """Keep development credentials separate; production keeps its legacy key."""
        if self.band_deployment is BandDeployment.PRODUCTION:
            return KEYRING_SERVICE
        return f"{KEYRING_SERVICE}.{self.band_deployment.value}"

    @property
    def local_state_directory(self) -> Path:
        """Keep per-deployment rooms, profiles, and supervisors isolated."""
        root = Path.home() / LOCAL_STATE_DIRNAME
        if self.band_deployment is BandDeployment.PRODUCTION:
            return root
        return root / self.band_deployment.value

    def local_state_path(self, filename: str) -> Path:
        """Return a deployment-scoped local-state file path."""
        return self.local_state_directory / filename


def load_settings() -> Settings:
    return Settings()
