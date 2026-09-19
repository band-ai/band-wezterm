"""Band platform facade — AsyncClientWrapper Bearer client (correction #6)."""

from __future__ import annotations

import contextlib
import re
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import Any
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
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from band_wezterm.auth.credentials import ManagedAgentKeyStore
from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.config import CHAT_MESSAGES_LIMIT, Settings, load_settings
from band_wezterm.identity import (
    AvatarKind,
    HarnessId,
    agent_accent,
    initials,
    parse_harness,
)
from band_wezterm.room_color import room_accent

Unsubscribe = Callable[[], None]


class ParticipantRole(StrEnum):
    MEMBER = "member"
    ADMIN = "admin"


class RealtimeEventKind(StrEnum):
    MESSAGE = "message"
    MESSAGE_CREATED = "message_created"
    MESSAGE_UPDATED = "message_updated"
    PARTICIPANT_JOINED = "participant_joined"
    PARTICIPANT_LEFT = "participant_left"
    UNKNOWN = "unknown"


class AgentRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    kind: AvatarKind
    color: str
    harness: HarnessId | None = None


class RoomRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    title: str
    color: str


class ParticipantRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: str
    kind: AvatarKind
    color: str


class MessageRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    content: str
    author_name: str


_MENTION_MARKUP = re.compile(r"@\[\[([0-9a-fA-F-]+)\]\]")


def display_message_content(
    content: str, metadata: Mapping[str, Any] | None = None
) -> str:
    """Turn platform `@[[uuid]]` mention markup into `@name` for the chat pane."""
    names: dict[str, str] = {}
    if metadata is not None:
        for item in metadata.get("mentions") or ():
            if not isinstance(item, Mapping):
                continue
            mention_id = item.get("id")
            if mention_id is None:
                continue
            label = item.get("name") or item.get("handle") or mention_id
            names[str(mention_id)] = str(label)
    return _MENTION_MARKUP.sub(
        lambda match: f"@{names.get(match.group(1), match.group(1))}", content
    )


def message_record_from_api(message: object) -> MessageRecord:
    """Map a Fern ChatMessage (or compatible object) into the host record."""
    metadata = getattr(message, "metadata", None)
    meta = metadata if isinstance(metadata, Mapping) else None
    content = str(getattr(message, "content", "") or "")
    sender_name = getattr(message, "sender_name", None)
    sender_id = getattr(message, "sender_id", None)
    return MessageRecord(
        id=str(message.id),
        content=display_message_content(content, meta),
        author_name=str(sender_name or sender_id or "unknown"),
    )


class RealtimeEvent(BaseModel):
    model_config = ConfigDict(frozen=True)

    kind: RealtimeEventKind
    room_id: str | None = None
    payload: Mapping[str, Any] | None = None


class DirectoryEntry(BaseModel):
    """Loose public-directory row — only id/name are required for Discover."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str | None = None
    uuid: str | None = None
    name: str | None = None

    def as_agent(self) -> AgentRecord | None:
        agent_id = self.id or self.uuid
        if not agent_id:
            return None
        return AgentRecord(
            id=str(agent_id),
            name=self.name or str(agent_id),
            kind=AvatarKind.AGENT,
            color=agent_accent(agent_id),
        )


class DirectoryResponse(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    data: list[DirectoryEntry] = Field(default_factory=list)
    agents: list[DirectoryEntry] = Field(default_factory=list)

    def entries(self) -> list[DirectoryEntry]:
        return self.data or self.agents


def _avatar_kind_from_platform(raw: object) -> AvatarKind:
    label = str(raw or "").lower()
    if label in {"agent", "bot"}:
        return AvatarKind.AGENT
    return AvatarKind.HUMAN


def _realtime_kind(raw: object) -> RealtimeEventKind:
    try:
        return RealtimeEventKind(str(raw))
    except ValueError:
        return RealtimeEventKind.UNKNOWN


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
        self._http = httpx.AsyncClient(timeout=60.0)
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

    @property
    def _token_generation(self) -> int:
        if self._host_auth is None:
            return 0
        return self._host_auth.token_generation

    async def _fetch_token(self) -> str:
        if self._api_key is not None:
            return self._api_key
        assert self._host_auth is not None
        return await self._host_auth.get_access_token()

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
        records: list[AgentRecord] = []
        for agent in response.data or []:
            agent_id = str(agent.id)
            agent_name = getattr(agent, "name", None) or agent_id
            harness_raw = getattr(agent, "harness", None) or getattr(
                agent, "runtime", None
            )
            harness = parse_harness(
                str(harness_raw) if harness_raw is not None else None
            )
            if harness is None:
                harness = self._agent_keys.get_harness(agent_id)
            records.append(
                AgentRecord(
                    id=agent_id,
                    name=agent_name,
                    kind=AvatarKind.AGENT,
                    color=agent_accent(agent_id),
                    harness=harness,
                )
            )
        return records

    async def create_agent(
        self,
        *,
        name: str,
        description: str,
        harness: HarnessId = HarnessId.CLAUDE_SDK,
    ) -> AgentRecord:
        """Registration-only — persists the one-time managed API key (INT-1484)."""
        response = await self._agents.register_my_agent(
            agent=AgentRegisterRequest(name=name, description=description)
        )
        agent = response.data.agent
        credentials = response.data.credentials
        agent_id = str(agent.id)
        agent_name = getattr(agent, "name", None) or name
        api_key = str(credentials.api_key)
        try:
            self._agent_keys.set(agent_id, api_key, harness=harness)
        except Exception:
            await self._rollback_agent_registration(agent_id)
            raise
        return AgentRecord(
            id=agent_id,
            name=agent_name,
            kind=AvatarKind.AGENT,
            color=agent_accent(agent_id),
            harness=harness,
        )

    async def _rollback_agent_registration(self, agent_id: str) -> None:
        with contextlib.suppress(Exception):
            await self._agents.delete_my_agent(agent_id, force=True)

    def managed_agent_api_key(self, agent_id: str) -> str | None:
        return self._agent_keys.get(agent_id)

    def update_managed_harness(
        self, agent_id: str, harness: HarnessId | str
    ) -> None:
        """Persist a reconfigured harness beside the existing managed API key."""
        api_key = self._agent_keys.get(agent_id)
        if not api_key:
            raise RuntimeError(
                "No managed API key for this agent — re-register it from Control."
            )
        self._agent_keys.set(agent_id, api_key, harness=harness)

    async def delete_agent(self, agent_id: str, *, force: bool = True) -> None:
        """Unregister a managed agent and drop its stored API key."""
        await self._agents.delete_my_agent(agent_id, force=force)
        self._agent_keys.delete(agent_id)

    async def list_my_chats(self) -> list[RoomRecord]:
        response = await self._chats.list_my_chats()
        rooms: list[RoomRecord] = []
        for chat in response.data or []:
            room_id = str(chat.id)
            title = getattr(chat, "title", None) or room_id
            rooms.append(
                RoomRecord(id=room_id, title=title, color=room_accent(room_id))
            )
        return rooms

    async def create_room(self, *, title: str | None = None) -> RoomRecord:
        response = await self._chats.create_my_chat_room(
            chat=CreateMyChatRoomRequestChat(title=title)
        )
        room_id = str(response.data.id)
        room_title = getattr(response.data, "title", None) or title or room_id
        return RoomRecord(
            id=room_id, title=room_title, color=room_accent(room_id)
        )

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
        participants: list[ParticipantRecord] = []
        for item in response.data or []:
            participant_id = str(item.id)
            name = getattr(item, "name", None) or participant_id
            kind_raw = getattr(item, "type", None) or getattr(item, "kind", None)
            participants.append(
                ParticipantRecord(
                    id=participant_id,
                    name=name,
                    kind=_avatar_kind_from_platform(kind_raw),
                    color=agent_accent(participant_id),
                )
            )
        return participants

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

    async def _ensure_realtime(self) -> None:
        if self._phx is not None and self._phx_generation == self._token_generation:
            return
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

    async def subscribe_room(self, room_id: str) -> None:
        await self._ensure_realtime()
        assert self._phx is not None

        async def handler(message: object) -> None:
            payload = getattr(message, "payload", None)
            event = RealtimeEvent(
                kind=_realtime_kind(getattr(message, "event", "message")),
                room_id=room_id,
                payload=payload if isinstance(payload, Mapping) else None,
            )
            for listener in list(self._realtime_listeners):
                listener(event)

        await self._phx.subscribe_to_topic(chat_room_topic(room_id), handler)
        await self._phx.subscribe_to_topic(room_participants_topic(room_id), handler)

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
        # Teardown is best-effort; socket/supervisor may already be gone.
        with contextlib.suppress(Exception):
            await client.shutdown("credential change or client close")


def avatar_label(name: str) -> str:
    return initials(name)
