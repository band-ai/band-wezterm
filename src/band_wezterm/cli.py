"""Typed public command tree for Band resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Annotated, Final

from cyclopts import App, Parameter

from band_wezterm.diagnostics import DEFAULT_LOG_TAIL_LINES

COMMAND_NAME: Final = "band"
SETUP_HELP: Final = (
    "Install or update the Band WezTerm plugin in the active WezTerm config "
    "(WEZTERM_CONFIG_FILE, ~/.wezterm.lua, or XDG wezterm.lua)."
)


class Command(StrEnum):
    SETUP = "setup"
    ROOM = "room"
    AGENT = "agent"
    STATUS = "status"
    LOGS = "logs"
    HELP = "help"
    LIST = "list"
    OPEN = "open"
    CREATE = "create"
    DELETE = "delete"
    CONFIGURE = "configure"
    START = "start"
    STOP = "stop"


SetupHandler = Callable[[], int]
ViewHandler = Callable[[str | None], int]
AgentViewHandler = Callable[[], int]
AsyncHandler = Callable[[], Awaitable[int]]
AgentListHandler = Callable[[bool], Awaitable[int]]
ReferenceHandler = Callable[[str], Awaitable[int]]
ConfigureAgentHandler = Callable[[str], int]
StopHandler = Callable[[str | None, bool], Awaitable[int]]
StatusHandler = Callable[[bool, bool], Awaitable[int]]
LogsHandler = Callable[[int], int]


def create_app(
    *,
    setup: SetupHandler,
    room_view: ViewHandler,
    agent_view: AgentViewHandler,
    create_agent: AgentViewHandler,
    configure_agent: ConfigureAgentHandler,
    rooms: AsyncHandler,
    agents: AgentListHandler,
    create_room: ReferenceHandler,
    delete_room: ReferenceHandler,
    delete_agent: ReferenceHandler,
    start_agent: ReferenceHandler,
    stop_agent: StopHandler,
    agent_status: ReferenceHandler,
    status: StatusHandler,
    logs: LogsHandler,
) -> App:
    """Build resource-oriented commands; UI is each resource's default."""
    app = App(
        name=COMMAND_NAME,
        help="Manage Band rooms and detached agents in WezTerm.",
        result_action="return_int_as_exit_code_else_zero",
    )
    room_app = App(name=Command.ROOM, help="Manage Band rooms.")
    agent_app = App(name=Command.AGENT, help="Manage detached Band agents.")

    @app.default
    @app.command(name=Command.HELP)
    def help_command() -> int:
        app.help_print()
        return 0

    @app.command(name=Command.SETUP, help=SETUP_HELP)
    def setup_command() -> int:
        return setup()

    @app.command(name=Command.STATUS)
    async def status_command(*, room: bool = False, agent: bool = False) -> int:
        """Show Rooms and Agents, or one requested resource table."""
        if room and agent:
            raise ValueError("Use only one of --room or --agent.")
        return await status(room, agent)

    @app.command(name=Command.LOGS)
    def logs_command(*, tail: int = DEFAULT_LOG_TAIL_LINES) -> int:
        """Show recent rotating local diagnostics for incident investigation."""
        return logs(tail)

    @room_app.default
    def room_interactive() -> int:
        """Open the interactive Rooms surface."""
        return room_view(None)

    @room_app.command(name=Command.OPEN)
    def room_open(reference: str) -> int:
        """Open one room by exact title or ID."""
        return room_view(reference)

    @room_app.command(name=Command.LIST)
    async def room_list() -> int:
        """List accessible rooms."""
        return await rooms()

    @room_app.command(name=Command.CREATE)
    async def room_create(title: str) -> int:
        """Create a room with TITLE."""
        return await create_room(title)

    @room_app.command(name=Command.DELETE)
    async def room_delete(reference: str) -> int:
        """Delete one room by exact title or ID."""
        return await delete_room(reference)

    @agent_app.default
    def agent_interactive() -> int:
        """Open the interactive Agents surface."""
        return agent_view()

    @agent_app.command(name=Command.LIST)
    async def agent_list(
        *,
        verbose: Annotated[bool, Parameter(name=("--verbose", "-v"))] = False,
    ) -> int:
        """List registered agents; include runtime details with --verbose / -v."""
        return await agents(verbose)

    @agent_app.command(name=Command.CREATE)
    def agent_create() -> int:
        """Open the agent registration surface."""
        return create_agent()

    @agent_app.command(name=Command.CONFIGURE)
    def agent_configure(reference: str) -> int:
        """Open the reconfiguration surface for one existing agent."""
        return configure_agent(reference)

    @agent_app.command(name=Command.START)
    async def agent_start(reference: str) -> int:
        """Start one detached managed agent."""
        return await start_agent(reference)

    @agent_app.command(name=Command.STOP)
    async def agent_stop(reference: str | None = None, *, all: bool = False) -> int:
        """Gracefully stop one agent, or every agent with --all."""
        if all == (reference is not None):
            raise ValueError("Provide an agent reference or use --all.")
        return await stop_agent(reference, all)

    @agent_app.command(name=Command.STATUS)
    async def agent_status_command(reference: str) -> int:
        """Show one managed agent's runtime state."""
        return await agent_status(reference)

    @agent_app.command(name=Command.DELETE)
    async def agent_delete(reference: str) -> int:
        """Stop and delete one managed agent."""
        return await delete_agent(reference)

    app.command(room_app)
    app.command(agent_app)
    return app
