"""HostAuth refresh: keep reusable refresh_token; bump generation."""

from __future__ import annotations

import pytest

from band_wezterm.auth.credentials import TokenStore, UserTokens
from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.config import Settings


class _MemoryStore(TokenStore):
    def __init__(self) -> None:
        self._tokens: UserTokens | None = None

    def get_user_tokens(self) -> UserTokens | None:
        return self._tokens

    def set_user_tokens(self, tokens: UserTokens) -> None:
        self._tokens = tokens

    def delete_user_tokens(self) -> None:
        self._tokens = None


@pytest.mark.asyncio
async def test_refresh_keeps_prior_refresh_token_when_omitted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _MemoryStore()
    store.set_user_tokens(
        UserTokens(access_token="old-at", refresh_token="keep-me", expires_at=0)
    )
    auth = HostAuth(
        Settings(band_oauth_client_id="client"),
        store,
        now=lambda: 1_000.0,
    )

    async def fake_discover() -> object:
        class Meta:
            authorization_endpoint = "https://auth.band.ai/oauth/authorize"
            token_endpoint = "https://auth.band.ai/oauth/token"

        return Meta()

    async def fake_exchange(
        token_endpoint: str,
        form: dict[str, str],
        *,
        prior_refresh_token: str | None = None,
    ) -> UserTokens:
        assert form["grant_type"] == "refresh_token"
        assert prior_refresh_token == "keep-me"
        return UserTokens(
            access_token="new-at",
            refresh_token=prior_refresh_token or "",
            expires_at=2_000_000,
        )

    monkeypatch.setattr(auth, "_discover", fake_discover)
    monkeypatch.setattr(auth, "_exchange", fake_exchange)

    before = auth.token_generation
    token = await auth.get_access_token()
    assert token == "new-at"
    assert auth.token_generation == before + 1
    stored = store.get_user_tokens()
    assert stored is not None
    assert stored.refresh_token == "keep-me"
    assert stored.access_token == "new-at"


def test_room_topics_match_sdk_core() -> None:
    from band_sdk_core import chat_room_topic, room_participants_topic

    room_id = "11111111-1111-1111-1111-111111111111"
    assert chat_room_topic(room_id) == f"chat_room:{room_id}"
    assert room_participants_topic(room_id) == f"room_participants:{room_id}"
