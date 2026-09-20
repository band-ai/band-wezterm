"""Band platform facade — AsyncClientWrapper Bearer client (correction #6)."""

from __future__ import annotations

import contextlib
from collections.abc import Awaitable, Callable, Mapping
from uuid import UUID

import httpx
from band_rest.core.client_wrapper import AsyncClientWrapper
from band_rest.human_api_agents.client import AsyncHumanApiAgentsClient
from band_rest.human_api_chats.client import AsyncHumanApiChatsClient
from band_rest.human_api_chats.types.create_my_chat_room_request_chat import (
    CreateMyChatRoomRequestChat,
)
from band_rest.human_api_messages.client import AsyncHumanApiMessagesClient
from band_rest.human_api_participants.client import AsyncHumanApiParticipantsClient
from band_rest.human_api_profile.client import AsyncHumanApiProfileClient
from band_rest.types.agent_register_request import AgentRegisterRequest
from band_rest.types.chat_message_request import ChatMessageRequest
from band_rest.types.chat_message_request_mentions_item import (
    ChatMessageRequestMentionsItem,
)
from band_rest.types.participant_request import ParticipantRequest
from band_sdk_core import chat_room_topic, room_participants_topic
from phoenix_channels_python_client.client import (
    PhoenixChannelsProtocolVersion,
    PHXChannelsClient,
)
from pydantic import ValidationError

from band_wezterm.auth.credentials import ManagedAgentKeyStore, NoApiKeyError
from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.config import CHAT_MESSAGES_LIMIT, Settings, load_settings
from band_wezterm.diagnostics import log_event
from band_wezterm.platform_models import (
    AgentRecord,
    DirectoryResponse,
    MessageRecord,
    ParticipantRecord,
    ParticipantRole,
    RealtimeEvent,
    RealtimeEventKind,
    RoomRecord,
    agent_record_from_api,
    avatar_label,
    display_message_content,
    message_record_from_api,
    participant_record_from_api,
    realtime_event_kind,
    room_record_from_api,
)

Unsubscribe = Callable[[], None]
AuthenticationRejectedHandler = Callable[[int], None]
UNAUTHORIZED_STATUS = 401
AUTH_GENERATION_EXTENSION = "band_wezterm.auth_generation"

# Compatibility boundary: UI and integrations import stable records from here.
__all__ = (
    "AgentRecord",
    "BandClient",
    "MessageRecord",
    "ParticipantRecord",
    "ParticipantRole",
    "RealtimeEvent",
    "RealtimeEventKind",
    "RoomRecord",
    "Unsubscribe",
    "avatar_label",
    "display_message_content",
    "message_record_from_api",
)


class BandClient:
    """The only door to the platform. Screens never import band_rest."""

    def __init__(
        self,
        host_auth: HostAuth,
        settings: Settings | None = None,
        *,
        agent_keys: ManagedAgentKeyStore | None = None,
    ) -> None:
        self._configure(
            host_auth=host_auth,
            api_key=None,
            settings=settings,
            agent_keys=agent_keys,
        )

    @classmethod
    def from_user_api_key(
        cls,
        api_key: str,
        settings: Settings | None = None,
        *,
        agent_keys: ManagedAgentKeyStore | None = None,
    ) -> BandClient:
        """Live-test / harness path — ``X-API-Key`` like sdk-python fixtures."""
        client = cls.__new__(cls)
        client._configure(
            host_auth=None,
            api_key=api_key,
            settings=settings,
            agent_keys=agent_keys,
        )
        return client

    def _configure(
        self,
        *,
        host_auth: HostAuth | None,
        api_key: str | None,
        settings: Settings | None,
        agent_keys: ManagedAgentKeyStore | None = None,
    ) -> None:
        self._host_auth = host_auth
        self._api_key = api_key
        self._agent_keys = agent_keys or ManagedAgentKeyStore()
        self._settings = settings or load_settings()
        self._authentication_rejected_handler: AuthenticationRejectedHandler | None = None
        self._http = httpx.AsyncClient(
            timeout=60.0,
            event_hooks={
                "request": [self._tag_credential_generation],
                "response": [self._observe_response],
            },
        )
        self._wrapper = AsyncClientWrapper(
            api_key=api_key or "",
            base_url=self._settings.band_base_url.rstrip("/"),
            async_token=None if api_key is not None else self._bearer_token,
            httpx_client=self._http,
        )
        self._agents = AsyncHumanApiAgentsClient(client_wrapper=self._wrapper)
        self._chats = AsyncHumanApiChatsClient(client_wrapper=self._wrapper)
        self._participants = AsyncHumanApiParticipantsClient(
            client_wrapper=self._wrapper
        )
        self._messages = AsyncHumanApiMessagesClient(client_wrapper=self._wrapper)
        self._profile = AsyncHumanApiProfileClient(client_wrapper=self._wrapper)
        self._phx: PHXChannelsClient | None = None
        self._phx_generation: int | None = None
        self._realtime_listeners: list[Callable[[RealtimeEvent], None]] = []
        self._realtime_rooms: set[str] = set()

    @property
    def _token_generation(self) -> int:
        if self._host_auth is None:
            return 0
        return self._host_auth.token_generation

    async def _fetch_token(self) -> str:
        if self._api_key is not None:
            return self._api_key
        assert self._host_auth is not None
        try:
            return await self._host_auth.get_access_token()
        except NoApiKeyError:
            self._notify_authentication_rejected(self._token_generation)
            raise

    def set_authentication_rejected_handler(
        self, handler: AuthenticationRejectedHandler | None
    ) -> None:
        """Register the host's response to a rejected user credential."""
        self._authentication_rejected_handler = handler

    async def _tag_credential_generation(self, request: httpx.Request) -> None:
        if self._api_key is None:
            request.extensions[AUTH_GENERATION_EXTENSION] = self._token_generation

    async def _observe_response(self, response: httpx.Response) -> None:
        if self._api_key is None and response.status_code == UNAUTHORIZED_STATUS:
            self._notify_authentication_rejected(
                self._response_credential_generation(response)
            )

    def _response_credential_generation(self, response: httpx.Response) -> int:
        try:
            value = response.request.extensions.get(AUTH_GENERATION_EXTENSION)
        except RuntimeError:
            return self._token_generation
        return value if isinstance(value, int) else self._token_generation

    def _notify_authentication_rejected(self, generation: int) -> None:
        if generation != self._token_generation:
            log_event(
                "ignored stale authentication rejection",
                credential_generation=generation,
                current_generation=self._token_generation,
            )
            return
        if self._authentication_rejected_handler is not None:
            self._authentication_rejected_handler(self._token_generation)

    async def _bearer_token(self) -> str:
        """OAuth token for REST; reconnects realtime when generation rotates."""
        token = await self._fetch_token()
        if self._phx is not None and self._phx_generation != self._token_generation:
            await self.reset_realtime_after_credential_change()
        return token

    async def aclose(self) -> None:
        await self._disconnect_realtime()
        await self._http.aclose()

    async def whoami(self) -> str:
        response = await self._profile.get_my_profile()
        return response.data.id

    async def list_my_agents(self, *, name: str | None = None) -> list[AgentRecord]:
        response = await self._agents.list_my_agents(name=name)
        return [agent_record_from_api(agent) for agent in response.data or ()]

    async def create_agent(
        self,
        *,
        name: str,
        description: str,
    ) -> AgentRecord:
        """Registration-only — persists the one-time managed API key (INT-1484)."""
        response = await self._agents.register_my_agent(
            agent=AgentRegisterRequest(name=name, description=description)
        )
        agent = response.data.agent
        credentials = response.data.credentials
        api_key = str(credentials.api_key)
        try:
            self._agent_keys.set(str(agent.id), api_key)
        except Exception:
            await self._rollback_agent_registration(str(agent.id))
            raise
        return agent_record_from_api(agent, fallback_name=name)

    async def _rollback_agent_registration(self, agent_id: str) -> None:
        with contextlib.suppress(Exception):
            await self._agents.delete_my_agent(agent_id, force=True)

    def managed_agent_api_key(self, agent_id: str) -> str | None:
        return self._agent_keys.get(agent_id)

    async def delete_agent(self, agent_id: str, *, force: bool = True) -> None:
        """Unregister a managed agent and drop its stored API key."""
        await self._agents.delete_my_agent(agent_id, force=force)
        self._agent_keys.delete(agent_id)

    async def list_my_chats(self) -> list[RoomRecord]:
        response = await self._chats.list_my_chats()
        return [room_record_from_api(chat) for chat in response.data or ()]

    async def create_room(self, *, title: str | None = None) -> RoomRecord:
        response = await self._chats.create_my_chat_room(
            chat=CreateMyChatRoomRequestChat(title=title)
        )
        return room_record_from_api(response.data, fallback_title=title)

    async def delete_room(self, room_id: UUID | str) -> None:
        """Permanently delete a chat room (not in the Fern chats client yet)."""
        credential = await self._bearer_token()
        url = (
            f"{self._settings.band_base_url.rstrip('/')}"
            f"/api/v1/me/chats/{room_id}"
        )
        headers = (
            {"X-API-Key": credential}
            if self._api_key is not None
            else {"Authorization": f"Bearer {credential}"}
        )
        response = await self._http.delete(url, headers=headers)
        response.raise_for_status()

    async def list_participants(self, room_id: UUID | str) -> list[ParticipantRecord]:
        response = await self._participants.list_my_chat_participants(str(room_id))
        return [participant_record_from_api(item) for item in response.data or ()]

    async def add_participant(
        self,
        room_id: UUID | str,
        participant_id: UUID | str,
        *,
        role: ParticipantRole = ParticipantRole.MEMBER,
    ) -> None:
        await self._participants.add_my_chat_participant(
            str(room_id),
            participant=ParticipantRequest(
                participant_id=str(participant_id), role=role.value
            ),
        )

    async def remove_participant(
        self, room_id: UUID | str, participant_id: UUID | str
    ) -> None:
        await self._participants.remove_my_chat_participant(
            str(room_id), str(participant_id)
        )

    async def send_message(
        self,
        room_id: UUID | str,
        body: str,
        *,
        mention_id: str,
        mention_name: str,
    ) -> MessageRecord:
        response = await self._messages.send_my_chat_message(
            str(room_id),
            message=ChatMessageRequest(
                content=f"@{mention_name} {body}",
                mentions=[
                    ChatMessageRequestMentionsItem(id=mention_id, name=mention_name)
                ],
            ),
        )
        return message_record_from_api(response.data)

    async def list_messages(
        self,
        room_id: UUID | str,
        *,
        limit: int = CHAT_MESSAGES_LIMIT,
    ) -> list[MessageRecord]:
        """Latest page of room history, oldest-first (plugin fetchLatestMessages)."""
        response = await self._messages.list_my_chat_messages(
            str(room_id), limit=limit
        )
        rows = list(response.data or [])
        rows.reverse()
        return [message_record_from_api(message) for message in rows]

    async def list_directory(self) -> list[AgentRecord]:
        """Public opt-in Discover directory — distinct from Agents search."""
        credential = await self._bearer_token()
        url = f"{self._settings.band_base_url.rstrip('/')}/api/v1/me/directory"
        headers = (
            {"X-API-Key": credential}
            if self._api_key is not None
            else {"Authorization": f"Bearer {credential}"}
        )
        response = await self._http.get(url, headers=headers)
        if response.status_code == 404:
            return []
        response.raise_for_status()
        try:
            parsed = DirectoryResponse.model_validate(response.json())
        except ValidationError:
            return []
        records: list[AgentRecord] = []
        for entry in parsed.entries():
            agent = entry.as_agent()
            if agent is not None:
                records.append(agent)
        return records

    def subscribe_realtime(
        self, on_event: Callable[[RealtimeEvent], None]
    ) -> Unsubscribe:
        self._realtime_listeners.append(on_event)

        def unsubscribe() -> None:
            if on_event in self._realtime_listeners:
                self._realtime_listeners.remove(on_event)

        return unsubscribe

    async def unsubscribe_room(self, room_id: str) -> None:
        """Release a detail screen's topics when it closes."""
        if room_id not in self._realtime_rooms:
            return
        self._realtime_rooms.remove(room_id)
        if self._phx is None:
            return
        for topic in (chat_room_topic(room_id), room_participants_topic(room_id)):
            with contextlib.suppress(Exception):
                await self._phx.unsubscribe_from_topic(topic)

    async def _ensure_realtime(self) -> bool:
        if self._phx is not None and self._phx_generation == self._token_generation:
            return False
        await self._disconnect_realtime()
        token = await self._fetch_token()
        generation = self._token_generation
        ws_url = self._settings.band_ws_url.rstrip("/")
        headers = (
            {"x-api-key": token}
            if self._api_key is not None
            else {"x-auth-token": token}
        )
        client = PHXChannelsClient(
            ws_url,
            token,
            protocol_version=PhoenixChannelsProtocolVersion.V2,
            additional_headers=headers,
        )
        await client.__aenter__()
        self._phx = client
        self._phx_generation = generation
        for room_id in self._realtime_rooms:
            await self._subscribe_room_topics(room_id)
        log_event("realtime connected", credential_generation=generation)
        return True

    async def subscribe_room(self, room_id: str) -> None:
        """Keep one room's topics live across reconnects and detail remounts."""
        if room_id in self._realtime_rooms:
            return
        self._realtime_rooms.add(room_id)
        try:
            if not await self._ensure_realtime():
                await self._subscribe_room_topics(room_id)
        except Exception:
            self._realtime_rooms.discard(room_id)
            raise

    async def _subscribe_room_topics(self, room_id: str) -> None:
        """Attach both room topics to the current socket exactly once."""
        await self._ensure_realtime()
        assert self._phx is not None
        topics = (chat_room_topic(room_id), room_participants_topic(room_id))
        try:
            for topic in topics:
                await self._phx.subscribe_to_topic(topic, self._realtime_handler(room_id))
        except Exception:
            for topic in topics:
                with contextlib.suppress(Exception):
                    await self._phx.unsubscribe_from_topic(topic)
            raise

    def _realtime_handler(self, room_id: str) -> Callable[[object], Awaitable[None]]:
        async def handler(message: object) -> None:
            payload = getattr(message, "payload", None)
            event = RealtimeEvent(
                kind=realtime_event_kind(getattr(message, "event", "message")),
                room_id=room_id,
                payload=payload if isinstance(payload, Mapping) else None,
            )
            for listener in list(self._realtime_listeners):
                listener(event)

        return handler

    async def reset_realtime_after_credential_change(self) -> None:
        """Reconnect the socket after HostAuth rotation (listeners stay registered)."""
        await self._disconnect_realtime()
        if self._realtime_listeners:
            await self._ensure_realtime()

    async def _disconnect_realtime(self) -> None:
        if self._phx is None:
            return
        client = self._phx
        self._phx = None
        self._phx_generation = None
        log_event("realtime disconnected")
        # Teardown is best-effort; socket/supervisor may already be gone.
        with contextlib.suppress(Exception):
            await client.shutdown("credential change or client close")
