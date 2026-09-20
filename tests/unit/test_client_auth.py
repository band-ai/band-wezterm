"""BandClient reports invalid user credentials through one boundary."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, create_autospec

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


@pytest.mark.asyncio
async def test_room_subscription_is_idempotent_and_released() -> None:
    client = BandClient.from_user_api_key("band_test", Settings())
    phx = MagicMock()
    phx.subscribe_to_topic = AsyncMock()
    phx.unsubscribe_from_topic = AsyncMock()
    client._phx = phx
    client._phx_generation = client._token_generation

    await client.subscribe_room("room-1")
    await client.subscribe_room("room-1")

    assert phx.subscribe_to_topic.await_count == 2
    await client.unsubscribe_room("room-1")
    assert phx.unsubscribe_from_topic.await_count == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_failed_room_subscription_does_not_leave_a_stale_registration() -> None:
    client = BandClient.from_user_api_key("band_test", Settings())
    phx = MagicMock()
    phx.subscribe_to_topic = AsyncMock(side_effect=RuntimeError("socket lost"))
    client._phx = phx
    client._phx_generation = client._token_generation

    with pytest.raises(RuntimeError, match="socket lost"):
        await client.subscribe_room("room-1")

    assert client._realtime_rooms == set()
    await client.aclose()
