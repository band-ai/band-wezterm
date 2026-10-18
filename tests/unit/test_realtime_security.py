"""Exercise the host's real Phoenix transport with synthetic credentials."""

from __future__ import annotations

import asyncio
import json
import logging
from unittest.mock import AsyncMock, create_autospec
from urllib.parse import parse_qsl, quote, quote_plus, urlsplit

import pytest
from websockets.asyncio.server import ServerConnection, serve
from websockets.http11 import Request

from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.client import BandClient
from band_wezterm.config import Settings


class TestRealtimeCredentialSecurity:
    @pytest.mark.parametrize("authentication", ["api-key", "jwt"])
    async def test_initial_and_reconnected_socket_keep_credentials_in_headers(
        self, authentication: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        credential = "synthetic/private+ credential?x=1&z=#[]"
        requests: list[Request] = []
        delivered = asyncio.Event()

        async def peer(connection: ServerConnection) -> None:
            assert connection.request is not None
            requests.append(connection.request)
            joins = 0
            async for message in connection:
                join_ref, ref, topic, event, _payload = json.loads(message)
                if event == "phx_join":
                    joins += 1
                await connection.send(
                    json.dumps(
                        [
                            join_ref,
                            ref,
                            topic,
                            "phx_reply",
                            {"status": "ok", "response": {}},
                        ]
                    )
                )
                if joins == 2:
                    if len(requests) == 1:
                        await connection.close(code=1012, reason=credential)
                        return
                    await connection.send(
                        json.dumps(
                            [join_ref, None, topic, "synthetic_after_reconnect", {}]
                        )
                    )

        caplog.set_level(logging.DEBUG, logger="phoenix_channels_python_client.client")
        caplog.set_level(logging.INFO, logger="band_wezterm")
        async with serve(peer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            settings = Settings(BAND_WS_URL=f"ws://127.0.0.1:{port}/socket/websocket")
            if authentication == "api-key":
                client = BandClient.from_user_api_key(credential, settings)
                expected_header = "x-api-key"
            else:
                auth = create_autospec(HostAuth, instance=True)
                auth.token_generation = 1
                auth.get_access_token = AsyncMock(return_value=credential)
                client = BandClient(auth, settings)
                expected_header = "x-auth-token"
            client.subscribe_realtime(lambda _event: delivered.set())
            try:
                await client.subscribe_room("synthetic-room")
                await asyncio.wait_for(delivered.wait(), timeout=15)
            finally:
                await client.aclose()

        assert len(requests) == 2
        for request in requests:
            assert parse_qsl(urlsplit(request.path).query) == [("vsn", "2.0.0")]
            assert request.headers[expected_header] == credential
            assert (
                request.headers.get(
                    "x-auth-token" if authentication == "api-key" else "x-api-key"
                )
                is None
            )
        records = [
            record
            for record in caplog.records
            if record.name in {"phoenix_channels_python_client.client", "band_wezterm"}
        ]
        assert records
        variants = {
            credential,
            quote(credential, safe=""),
            quote(credential),
            quote_plus(credential),
        }
        assert all(
            value not in repr(vars(record)) for record in records for value in variants
        )
