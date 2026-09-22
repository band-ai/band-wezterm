"""Typed Band command routing."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Final

from cyclopts import App

COMMAND_NAME: Final = "band"
SETUP_HELP: Final = (
    "Install or update the Band WezTerm plugin in the active WezTerm config "
    "(WEZTERM_CONFIG_FILE, ~/.wezterm.lua, or XDG wezterm.lua)."
)


class Command(StrEnum):
    SETUP = "setup"
    ROOM = "room"
    ROOMS = "rooms"
    AGENT = "agent"
    AGENTS = "agents"
    STATUS = "status"
    HELP = "help"


class AgentAction(StrEnum):
    START = "start"
    STOP = "stop"
    STATUS = "status"


AGENT_ACTION_HELP: Final[dict[AgentAction, str]] = {
    AgentAction.START: "Start a detached managed agent.",
    AgentAction.STOP: "Gracefully stop a detached managed agent.",
    AgentAction.STATUS: "Show one managed agent's runtime state.",
}


SetupHandler = Callable[[], int]
RoomHandler = Callable[[str | None], int]
AsyncHandler = Callable[[], Awaitable[int]]
AgentHandler = Callable[[AgentAction, str], Awaitable[int]]


def create_app(
    *,
    setup: SetupHandler,
    room: RoomHandler,
    rooms: AsyncHandler,
    agents: AsyncHandler,
    status: AsyncHandler,
    agent: AgentHandler,
) -> App:
    """Create the complete public command tree from typed operation handlers."""
    app = App(
        name=COMMAND_NAME,
        help=(
            "Open and manage Band rooms and detached agents. "
            "Use `band room` to open the room view."
        ),
        result_action="return_int_as_exit_code_else_zero",
    )
    agent_app = App(name=Command.AGENT.value, help="Operate one managed agent.")

    @app.default
    def help_command() -> int:
        app.help_print()
        return 0

    @app.command(name=Command.HELP.value)
    def explicit_help_command() -> int:
        app.help_print()
        return 0

    @app.command(name=Command.SETUP.value, help=SETUP_HELP)
    def setup_command() -> int:
        """Install or update the Band WezTerm plugin in the active config."""
        return setup()

    @app.command(name=Command.ROOM.value)
    def room_command(reference: str | None = None) -> int:
        """Open a room by title or ID, or choose a room."""
        return room(reference)

    @app.command(name=Command.ROOMS.value)
    async def rooms_command() -> int:
        """List accessible rooms."""
        return await rooms()

    @app.command(name=Command.AGENTS.value)
    async def agents_command() -> int:
        """List registered agents and their runtime state."""
        return await agents()

    @app.command(name=Command.STATUS.value)
    async def status_command() -> int:
        """List rooms and agents with their direct commands."""
        return await status()

    for action in AgentAction:
        agent_app.command(
            _agent_command(agent, action),
            name=action.value,
            help=AGENT_ACTION_HELP[action],
        )
    app.command(agent_app)
    return app


def _agent_command(
    agent: AgentHandler, action: AgentAction
) -> Callable[[str], Awaitable[int]]:
    async def command(agent_id: str) -> int:
        return await agent(action, agent_id)

    return command
