"""Platform catalog reads shared by full-screen and split views."""

from __future__ import annotations

from band_wezterm.client import AgentRecord, BandClient, RoomRecord
from band_wezterm.managed_profiles import ManagedAgentStore


async def list_managed_agents(
    client: BandClient,
    profiles: ManagedAgentStore,
    *,
    name: str | None = None,
) -> list[AgentRecord]:
    """Read the human's agents and overlay durable local harness metadata."""
    agents = await client.list_my_agents(name=name)
    return [
        agent.model_copy(update={"harness": harness})
        if (harness := profiles.harness_for(agent.id)) is not None
        and harness is not agent.harness
        else agent
        for agent in agents
    ]


async def list_rooms(client: BandClient) -> list[RoomRecord]:
    """Read the human's room catalog."""
    return await client.list_my_chats()
