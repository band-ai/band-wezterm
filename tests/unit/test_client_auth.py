"""BandClient reports invalid user credentials through one boundary."""

from __future__ import annotations

from unittest.mock import create_autospec

import httpx
import pytest

from band_wezterm.auth.credentials import NoApiKeyError
from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.client import BandClient
from band_wezterm.config import Settings


@pytest.mark.asyncio
async def test_unauthorized_user_response_notifies_host() -> None:
    auth = create_autospec(HostAuth, instance=True)
    client = BandClient(auth, Settings())
    rejected: list[None] = []
    client.set_authentication_rejected_handler(lambda: rejected.append(None))

    await client._observe_response(httpx.Response(401))

    assert rejected == [None]
    await client.aclose()


@pytest.mark.asyncio
async def test_missing_local_session_notifies_host() -> None:
    auth = create_autospec(HostAuth, instance=True)
    auth.get_access_token.side_effect = NoApiKeyError()
    client = BandClient(auth, Settings())
    rejected: list[None] = []
    client.set_authentication_rejected_handler(lambda: rejected.append(None))

    with pytest.raises(NoApiKeyError):
        await client._fetch_token()

    assert rejected == [None]
    await client.aclose()


@pytest.mark.asyncio
async def test_api_key_client_does_not_invalidate_user_session() -> None:
    client = BandClient.from_user_api_key("band_test", Settings())
    rejected: list[None] = []
    client.set_authentication_rejected_handler(lambda: rejected.append(None))

    await client._observe_response(httpx.Response(401))

    assert rejected == []
    await client.aclose()
