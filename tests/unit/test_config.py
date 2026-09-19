"""Host Settings defaults — shared public OAuth client, env override."""

from __future__ import annotations

import pytest

from band_wezterm.config import DEFAULT_OAUTH_CLIENT_ID, Settings


def test_oauth_client_id_defaults_to_shared_public_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BAND_OAUTH_CLIENT_ID", raising=False)
    settings = Settings(_env_file=None)
    assert settings.band_oauth_client_id == DEFAULT_OAUTH_CLIENT_ID


def test_oauth_client_id_env_overrides_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAND_OAUTH_CLIENT_ID", "other-tenant")
    settings = Settings(_env_file=None)
    assert settings.band_oauth_client_id == "other-tenant"
