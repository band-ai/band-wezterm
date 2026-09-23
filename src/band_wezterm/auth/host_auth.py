"""OAuth PKCE host auth — algorithmic port of UserAuth (userAuth.ts)."""

from __future__ import annotations

import asyncio
import threading
import time
import webbrowser
from collections.abc import Callable
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from band_wezterm.auth.credentials import NoApiKeyError, TokenStore, UserTokens
from band_wezterm.auth.pkce import code_challenge, code_verifier, random_base64url
from band_wezterm.config import (
    CALLBACK_PATH,
    OAUTH_SCOPES,
    REFRESH_EARLY_MS,
    Settings,
    load_settings,
)

DEFAULT_TOKEN_LIFETIME_SECONDS = 3_600
MINIMUM_TOKEN_LIFETIME_SECONDS = 1
INVALID_GRANT_ERROR = "invalid_grant"
SIGN_IN_TIMEOUT_S = 10 * 60
LOOPBACK_POLL_SECONDS = 0.2
SIGN_IN_CANCELLED_MESSAGE = "Band sign-in was cancelled."


class OidcMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)

    authorization_endpoint: str
    token_endpoint: str


class TokenResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None
    error: str | None = None
    error_description: str | None = None


class TokenExchangeError(Exception):
    def __init__(self, code: str | None, message: str) -> None:
        self.code = code
        super().__init__(message)


class HostAuth:
    """Owns token lifecycle. Nothing else caches an access token."""

    def __init__(
        self,
        settings: Settings | None = None,
        store: TokenStore | None = None,
        *,
        now: Callable[[], float] | None = None,
        open_browser: Callable[[str], bool] | None = None,
    ) -> None:
        self._settings = settings or load_settings()
        self._store = store or TokenStore(service=self._settings.keyring_service)
        self._now = now or time.time
        self._open_browser = open_browser or webbrowser.open
        self._token_generation = 0
        self._refresh_flight: asyncio.Task[str] | None = None
        self._refresh_generation: int | None = None
        self._lock = asyncio.Lock()
        self._oidc_metadata: OidcMetadata | None = None
        self._authorization_cancel: threading.Event | None = None

    @property
    def token_generation(self) -> int:
        return self._token_generation

    def has_stored_tokens(self) -> bool:
        return self._store.get_user_tokens() is not None

    async def get_access_token(self) -> str:
        generation = self._token_generation
        tokens = self._store.get_user_tokens()
        if tokens is None or generation != self._token_generation:
            raise NoApiKeyError()
        if tokens.expires_at > int(self._now() * 1000) + REFRESH_EARLY_MS:
            return tokens.access_token
        try:
            return await self._refresh_access_token(tokens, generation)
        except Exception as error:
            if _is_terminal_refresh_failure(error):
                await self._clear_user_tokens(generation)
                raise NoApiKeyError(str(error)) from error
            raise

    async def sign_in(self) -> None:
        if not self._settings.band_oauth_client_id:
            raise RuntimeError(
                "Band sign-in is unavailable because the OAuth client id is empty."
            )
        self.cancel_sign_in()
        generation = self._bump_generation()
        metadata = await self._discover()
        if generation != self._token_generation:
            raise RuntimeError("Band sign-in was superseded by a newer sign-in.")

        cancellation = threading.Event()
        self._authorization_cancel = cancellation
        verifier = code_verifier()
        state = random_base64url()
        server: _LoopbackServer | None = None
        callback_wait: asyncio.Task[str] | None = None
        try:
            server, port = await asyncio.to_thread(_start_loopback_server, state)
            redirect_uri = f"http://127.0.0.1:{port}{CALLBACK_PATH}"
            authorize_url = _build_authorize_url(
                metadata.authorization_endpoint,
                client_id=self._settings.band_oauth_client_id,
                redirect_uri=redirect_uri,
                state=state,
                challenge=code_challenge(verifier),
            )
            opened = self._open_browser(authorize_url)
            if not opened:
                raise RuntimeError("Could not open the sign-in browser.")
            callback_wait = asyncio.create_task(
                asyncio.to_thread(_wait_for_code, server, cancellation)
            )
            code = await asyncio.wait_for(
                asyncio.shield(callback_wait),
                timeout=SIGN_IN_TIMEOUT_S,
            )
            tokens = await self._exchange(
                metadata.token_endpoint,
                {
                    "grant_type": "authorization_code",
                    "client_id": self._settings.band_oauth_client_id,
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": verifier,
                },
            )
            if not await self._store_user_tokens(tokens, generation):
                raise RuntimeError("Band sign-in was superseded by a newer sign-in.")
        finally:
            cancellation.set()
            if callback_wait is not None:
                with suppress(Exception):
                    await callback_wait
            if server is not None:
                await asyncio.to_thread(server.server_close)
            if self._authorization_cancel is cancellation:
                self._authorization_cancel = None

    def cancel_sign_in(self) -> None:
        """End the active browser sign-in, if any."""
        if self._authorization_cancel is not None:
            self._authorization_cancel.set()

    async def sign_out(self) -> None:
        self._bump_generation()
        self._store.delete_user_tokens()

    def _bump_generation(self) -> int:
        self._token_generation += 1
        return self._token_generation

    async def _refresh_access_token(self, tokens: UserTokens, generation: int) -> str:
        async with self._lock:
            if not (
                self._refresh_flight is not None
                and self._refresh_generation == generation
                and not self._refresh_flight.done()
            ):
                self._refresh_generation = generation
                self._refresh_flight = asyncio.create_task(
                    self._refresh(tokens, generation)
                )
            flight = self._refresh_flight
        assert flight is not None
        try:
            return await flight
        finally:
            async with self._lock:
                if self._refresh_flight is flight:
                    self._refresh_flight = None
                    self._refresh_generation = None

    async def _refresh(self, tokens: UserTokens, generation: int) -> str:
        metadata = await self._discover()
        refreshed = await self._exchange(
            metadata.token_endpoint,
            {
                "grant_type": "refresh_token",
                "client_id": self._settings.band_oauth_client_id,
                "refresh_token": tokens.refresh_token,
            },
            prior_refresh_token=tokens.refresh_token,
        )
        if generation != self._token_generation:
            raise NoApiKeyError()
        new_generation = self._bump_generation()
        if not await self._store_user_tokens(refreshed, new_generation):
            raise NoApiKeyError()
        return refreshed.access_token

    async def _discover(self) -> OidcMetadata:
        if self._oidc_metadata is not None:
            return self._oidc_metadata
        issuer = self._settings.band_oauth_issuer.rstrip("/")
        url = f"{issuer}/.well-known/openid-configuration"
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            metadata = OidcMetadata.model_validate(response.json())
        _validate_endpoint(
            issuer, metadata.authorization_endpoint, "authorization_endpoint"
        )
        _validate_endpoint(issuer, metadata.token_endpoint, "token_endpoint")
        self._oidc_metadata = metadata
        return metadata

    async def _exchange(
        self,
        token_endpoint: str,
        form: dict[str, str],
        *,
        prior_refresh_token: str | None = None,
    ) -> UserTokens:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                token_endpoint,
                data=form,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        try:
            payload = TokenResponse.model_validate(response.json())
        except ValidationError as error:
            raise TokenExchangeError(
                None, f"Malformed token response: {error}"
            ) from error
        if response.status_code >= 400:
            raise TokenExchangeError(
                payload.error,
                payload.error_description or response.text,
            )
        if not payload.access_token:
            raise TokenExchangeError(None, "Token response missing access_token")
        refresh_token = payload.refresh_token or prior_refresh_token
        if not refresh_token:
            raise TokenExchangeError(None, "Token response missing refresh_token")
        lifetime = payload.expires_in or DEFAULT_TOKEN_LIFETIME_SECONDS
        lifetime_s = max(MINIMUM_TOKEN_LIFETIME_SECONDS, int(lifetime))
        expires_at = int(self._now() * 1000) + lifetime_s * 1000
        return UserTokens(
            access_token=payload.access_token,
            refresh_token=refresh_token,
            expires_at=expires_at,
        )

    async def _store_user_tokens(self, tokens: UserTokens, generation: int) -> bool:
        if generation != self._token_generation:
            return False
        self._store.set_user_tokens(tokens)
        return True

    async def _clear_user_tokens(self, generation: int) -> None:
        if generation != self._token_generation:
            return
        self._store.delete_user_tokens()


def _is_terminal_refresh_failure(error: object) -> bool:
    return isinstance(error, TokenExchangeError) and error.code == INVALID_GRANT_ERROR


def _validate_endpoint(issuer: str, endpoint: str, name: str) -> None:
    issuer_url = urlparse(issuer)
    endpoint_url = urlparse(endpoint)
    if (
        endpoint_url.scheme != issuer_url.scheme
        or endpoint_url.netloc != issuer_url.netloc
    ):
        raise RuntimeError(
            f"OIDC {name} origin does not match issuer ({endpoint} vs {issuer})"
        )


def _build_authorize_url(
    authorization_endpoint: str,
    *,
    client_id: str,
    redirect_uri: str,
    state: str,
    challenge: str,
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": OAUTH_SCOPES,
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    return f"{authorization_endpoint}?{query}"


class _CallbackHandler(BaseHTTPRequestHandler):
    server: _LoopbackServer

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != CALLBACK_PATH:
            self.send_response(404)
            self.end_headers()
            return
        params = parse_qs(parsed.query)
        state = (params.get("state") or [None])[0]
        code = (params.get("code") or [None])[0]
        if state != self.server.expected_state or not code:
            self.server.error = "invalid state or missing code"
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Sign-in failed.")
            return
        self.server.authorization_code = code
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sign-in complete. You can close this tab.")

    def log_message(self, format: str, *args: object) -> None:
        return


class _LoopbackServer(HTTPServer):
    def __init__(self, expected_state: str) -> None:
        super().__init__(("127.0.0.1", 0), _CallbackHandler)
        self.expected_state = expected_state
        self.timeout = LOOPBACK_POLL_SECONDS
        self.authorization_code: str | None = None
        self.error: str | None = None


def _start_loopback_server(state: str) -> tuple[_LoopbackServer, int]:
    server = _LoopbackServer(state)
    return server, int(server.server_address[1])


def _wait_for_code(server: _LoopbackServer, cancellation: threading.Event) -> str:
    while (
        server.authorization_code is None
        and server.error is None
        and not cancellation.is_set()
    ):
        server.handle_request()
    if cancellation.is_set():
        raise RuntimeError(SIGN_IN_CANCELLED_MESSAGE)
    if server.error:
        raise RuntimeError(server.error)
    assert server.authorization_code is not None
    return server.authorization_code
