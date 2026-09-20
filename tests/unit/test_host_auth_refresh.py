"""HostAuth refresh: keep reusable refresh_token; bump generation."""

from __future__ import annotations

import asyncio
from threading import Event, Thread
from urllib.parse import parse_qs, urlparse
from urllib.request import urlopen

import pytest

from band_wezterm.auth.credentials import NoApiKeyError, TokenStore, UserTokens
from band_wezterm.auth.host_auth import (
    SIGN_IN_CANCELLED_MESSAGE,
    HostAuth,
    TokenExchangeError,
)
from band_wezterm.config import Settings

CALLBACK_WAIT_START_TIMEOUT_SECONDS = 1


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


@pytest.mark.asyncio
async def test_invalid_refresh_token_clears_the_local_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _MemoryStore()
    store.set_user_tokens(
        UserTokens(access_token="old-at", refresh_token="revoked", expires_at=0)
    )
    auth = HostAuth(Settings(band_oauth_client_id="client"), store)

    async def failed_refresh(*_args: object, **_kwargs: object) -> UserTokens:
        raise TokenExchangeError("invalid_grant", "Refresh token revoked")

    monkeypatch.setattr(auth, "_refresh", failed_refresh)

    with pytest.raises(NoApiKeyError, match="Refresh token revoked"):
        await auth.get_access_token()

    assert store.get_user_tokens() is None


@pytest.mark.asyncio
async def test_concurrent_access_token_requests_share_one_refresh(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _MemoryStore()
    store.set_user_tokens(
        UserTokens(access_token="old-at", refresh_token="refresh", expires_at=0)
    )
    auth = HostAuth(Settings(band_oauth_client_id="client"), store)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def refresh(*_args: object, **_kwargs: object) -> str:
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        return "new-at"

    monkeypatch.setattr(auth, "_refresh", refresh)

    first = asyncio.create_task(auth.get_access_token())
    await started.wait()
    second = asyncio.create_task(auth.get_access_token())
    await asyncio.sleep(0)
    release.set()

    assert await asyncio.gather(first, second) == ["new-at", "new-at"]
    assert calls == 1


@pytest.mark.asyncio
async def test_cancel_sign_in_unblocks_the_callback_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    auth = HostAuth(Settings(band_oauth_client_id="client"), _MemoryStore())
    callback_started = Event()

    async def discover() -> object:
        class Metadata:
            authorization_endpoint = "https://auth.band.ai/authorize"
            token_endpoint = "https://auth.band.ai/token"

        return Metadata()

    monkeypatch.setattr(auth, "_discover", discover)
    monkeypatch.setattr(auth, "_open_browser", lambda _url: True)
    class FakeServer:
        def server_close(self) -> None:
            return

    def start_server(_state: str) -> tuple[FakeServer, int]:
        return FakeServer(), 12345

    def wait_for_code(_server: FakeServer, cancellation: Event) -> str:
        callback_started.set()
        cancellation.wait()
        raise RuntimeError(SIGN_IN_CANCELLED_MESSAGE)

    monkeypatch.setattr("band_wezterm.auth.host_auth._start_loopback_server", start_server)
    monkeypatch.setattr("band_wezterm.auth.host_auth._wait_for_code", wait_for_code)

    sign_in = asyncio.create_task(auth.sign_in())
    assert await asyncio.to_thread(
        callback_started.wait, CALLBACK_WAIT_START_TIMEOUT_SECONDS
    )
    auth.cancel_sign_in()

    with pytest.raises(RuntimeError, match=SIGN_IN_CANCELLED_MESSAGE):
        await sign_in


@pytest.mark.asyncio
async def test_sign_in_returns_after_the_browser_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _MemoryStore()

    def complete_callback(authorization_url: str) -> bool:
        parsed = urlparse(authorization_url)
        parameters = parse_qs(parsed.query)
        callback = urlparse(parameters["redirect_uri"][0])
        query = f"code=authorization-code&state={parameters['state'][0]}"
        redirect = callback._replace(query=query).geturl()
        Thread(target=lambda: urlopen(redirect, timeout=2).read()).start()
        return True

    auth = HostAuth(
        Settings(band_oauth_client_id="client"), store, open_browser=complete_callback
    )

    async def discover() -> object:
        class Metadata:
            authorization_endpoint = "https://auth.band.ai/authorize"
            token_endpoint = "https://auth.band.ai/token"

        return Metadata()

    async def exchange(
        _endpoint: str, form: dict[str, str], **_kwargs: object
    ) -> UserTokens:
        assert form["code"] == "authorization-code"
        return UserTokens(access_token="access", refresh_token="refresh", expires_at=1)

    monkeypatch.setattr(auth, "_discover", discover)
    monkeypatch.setattr(auth, "_exchange", exchange)

    await asyncio.wait_for(auth.sign_in(), timeout=2)

    assert store.get_user_tokens() is not None
