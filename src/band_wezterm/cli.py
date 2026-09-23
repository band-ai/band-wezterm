"""Typed public command tree for Band resources."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from enum import StrEnum
from typing import Annotated, Final

from cyclopts import App, Parameter

from band_wezterm.diagnostics import DEFAULT_LOG_TAIL_LINES
from band_wezterm.listing import DEFAULT_PAGE_SIZE, ListQuery

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
    COMPLETION = "completion"
    LIST = "list"
    OPEN = "open"
    CREATE = "create"
    DELETE = "delete"
    CONFIGURE = "configure"
    START = "start"
    STOP = "stop"


SetupHandler = Callable[[], int]
ViewHandler = Callable[[str | None], Awaitable[int]]
ListHandler = Callable[[ListQuery], Awaitable[int]]
AgentListHandler = Callable[[ListQuery, bool], Awaitable[int]]
ReferenceHandler = Callable[[str], Awaitable[int]]
ConfigureAgentHandler = Callable[[str], int]
StopHandler = Callable[[str | None, bool], Awaitable[int]]
StatusHandler = Callable[[bool, bool], Awaitable[int]]
LogsHandler = Callable[[int], int]


def create_app(
    *,
    setup: SetupHandler,
    room_view: ViewHandler,
    agent_view: ViewHandler,
    create_agent: Callable[[], int],
    configure_agent: ConfigureAgentHandler,
    rooms: ListHandler,
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
    app.register_install_completion_command(
        name=Command.COMPLETION,
        help="Install shell completion for Band commands.",
    )

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
    async def room_interactive(
        *,
        name: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> int:
        """Open Rooms, or list filtered rooms when an option is supplied."""
        query = ListQuery(name=name, limit=limit, offset=offset)
        if query.is_default:
            return await room_view(None)
        return await rooms(query)

    @room_app.command(name=Command.OPEN)
    async def room_open(reference: str) -> int:
        """Open one room by exact title or unique ID prefix."""
        return await room_view(reference)

    @room_app.command(name=Command.LIST)
    async def room_list(
        *,
        name: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
    ) -> int:
        """List rooms by name prefix in a bounded page."""
        return await rooms(ListQuery(name=name, limit=limit, offset=offset))

    @room_app.command(name=Command.CREATE)
    async def room_create(title: str) -> int:
        """Create a room with TITLE."""
        return await create_room(title)

    @room_app.command(name=Command.DELETE)
    async def room_delete(reference: str) -> int:
        """Delete one room by exact title or unique ID prefix."""
        return await delete_room(reference)

    @agent_app.default
    async def agent_interactive(
        reference: Annotated[
            str | None,
            Parameter(help="Exact agent name or a unique agent ID prefix."),
        ] = None,
        *,
        name: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        verbose: Annotated[bool, Parameter(name=("--verbose", "-v"))] = False,
    ) -> int:
        """Open the interactive Agents surface, optionally selecting one agent."""
        query = ListQuery(name=name, limit=limit, offset=offset)
        if reference is None and (not query.is_default or verbose):
            return await agents(query, verbose)
        if reference is not None and not query.is_default:
            raise ValueError("Use a reference or list filters, not both.")
        return await agent_view(reference)

    @agent_app.command(name=Command.LIST)
    async def agent_list(
        *,
        name: str | None = None,
        limit: int = DEFAULT_PAGE_SIZE,
        offset: int = 0,
        verbose: Annotated[bool, Parameter(name=("--verbose", "-v"))] = False,
    ) -> int:
        """List agents by name prefix in a bounded page."""
        return await agents(ListQuery(name=name, limit=limit, offset=offset), verbose)

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
