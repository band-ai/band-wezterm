"""Keyring-backed token store — port of credentials.ts (user tokens only)."""

from __future__ import annotations

import keyring
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from band_wezterm.config import KEYRING_SERVICE, KEYRING_USER_TOKENS


class UserTokens(BaseModel):
    """Persisted OAuth session — camelCase on disk to match the extension."""

    model_config = ConfigDict(frozen=True, populate_by_name=True)

    access_token: str = Field(alias="accessToken")
    refresh_token: str = Field(alias="refreshToken")
    expires_at: int = Field(alias="expiresAt")  # epoch ms


class NoApiKeyError(Exception):
    """Raised when no usable user sign-in is available."""

    def __init__(self, detail: str | None = None) -> None:
        message = (
            f"Band sign-in required: {detail}"
            if detail
            else "No Band sign-in found. Sign in from the Control tab first."
        )
        super().__init__(message)


class TokenStore:
    """Only host_auth.py touches keyring — screens never import this."""

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
