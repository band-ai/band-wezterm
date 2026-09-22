"""Keyring-backed stores — port of credentials.ts (user tokens + managed agent keys)."""

from __future__ import annotations

import keyring
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from band_wezterm.config import (
    KEYRING_MANAGED_AGENT_KEY_PREFIX,
    KEYRING_SERVICE,
    KEYRING_USER_TOKENS,
)


class UserTokens(BaseModel):
    """Persisted OAuth session — camelCase on disk to match the extension."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")
    expires_at: int = Field(alias="expiresAt")  # epoch ms


class ManagedAgentCredentials(BaseModel):
    """One-time agent API key; the launch profile owns all runtime settings."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    api_key: str = Field(alias="apiKey")


class NoApiKeyError(Exception):
    """Raised when no usable user sign-in is available."""

    def __init__(self, detail: str | None = None) -> None:
        message = (
            f"Band sign-in required: {detail}"
            if detail
            else "No Band sign-in found. Open `band room` or `band agent` to sign in."
        )
        super().__init__(message)


class TokenStore:
    """Only host_auth.py touches user tokens — screens never import this."""

    def __init__(
        self,
        *,
        service: str = KEYRING_SERVICE,
        username: str = KEYRING_USER_TOKENS,
    ) -> None:
        self._service = service
        self._username = username

    def get_user_tokens(self) -> UserTokens | None:
        raw = keyring.get_password(self._service, self._username)
        if not raw:
            return None
        try:
            return UserTokens.model_validate_json(raw)
        except ValidationError:
            return None

    def set_user_tokens(self, tokens: UserTokens) -> None:
        keyring.set_password(
            self._service,
            self._username,
            tokens.model_dump_json(by_alias=True),
        )

    def delete_user_tokens(self) -> None:
        try:
            keyring.delete_password(self._service, self._username)
        except keyring.errors.PasswordDeleteError:
            return


class ManagedAgentKeyStore:
    """Managed agent secrets — the keyring never owns launch configuration."""

    def __init__(self, *, service: str = KEYRING_SERVICE) -> None:
        self._service = service

    def _username(self, agent_id: str) -> str:
        return f"{KEYRING_MANAGED_AGENT_KEY_PREFIX}{agent_id}"

    def get_credentials(self, agent_id: str) -> ManagedAgentCredentials | None:
        raw = keyring.get_password(self._service, self._username(agent_id))
        if not raw:
            return None
        try:
            return ManagedAgentCredentials.model_validate_json(raw)
        except ValidationError:
            # Pre-JSON entries were a bare API key string.
            return ManagedAgentCredentials(api_key=raw)

    def get(self, agent_id: str) -> str | None:
        credentials = self.get_credentials(agent_id)
        return None if credentials is None else credentials.api_key

    def set(self, agent_id: str, api_key: str) -> None:
        record = ManagedAgentCredentials(api_key=api_key)
        keyring.set_password(
            self._service,
            self._username(agent_id),
            record.model_dump_json(by_alias=True),
        )

    def delete(self, agent_id: str) -> None:
        try:
            keyring.delete_password(self._service, self._username(agent_id))
        except keyring.errors.PasswordDeleteError:
            return
