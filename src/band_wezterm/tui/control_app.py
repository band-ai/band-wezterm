"""Control view for platform state and the detached local runtime."""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import suppress
from typing import ClassVar, Final

from textual.app import App
from textual.message import Message
from textual.screen import Screen

from band_wezterm.agent.opencode_server import OpenCodeServerManager
from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.catalogs import ModelCatalogService
from band_wezterm.client import BandClient, RoomRecord
from band_wezterm.config import (
    CONTROL_TAB_TITLE,
    WINDOW_TITLE,
    Settings,
    load_settings,
)
from band_wezterm.diagnostics import configure_diagnostics, log_event
from band_wezterm.errors import format_platform_error
from band_wezterm.local_state import StarredRooms
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.pane_identity import announce_control_human
from band_wezterm.preferences import PreferencesStore
from band_wezterm.supervisor import SupervisorClient
from band_wezterm.tui.host_pane import (
    WEZTERM_PANE_ENV,
    current_pane_id,
)
from band_wezterm.tui.refresh import PANE_POLL_SECONDS
from band_wezterm.tui.screens.agents import AgentsScreen
from band_wezterm.tui.screens.rooms import RoomDetailScreen, RoomsScreen
from band_wezterm.tui.screens.settings import SettingsScreen
from band_wezterm.tui.screens.sign_in import SignInScreen
from band_wezterm.tui.screens.workspace import WorkspaceScreen
from band_wezterm.tui.stores import AgentsStore, AgentStatusSource, RoomsStore
from band_wezterm.wezterm_cli import WezTermCliError, set_tab_title, set_window_title

CONTROL_PROCESS_ENV: Final = "BAND_WEZTERM_CONTROL"
CONTROL_PROCESS_FLAG: Final = "1"

SIGN_IN_SCREEN: Final = "sign_in"
WORKSPACE_SCREEN: Final = "workspace"
AGENTS_SCREEN: Final = "agents"
ROOMS_SCREEN: Final = "rooms"
SETTINGS_SCREEN: Final = "settings"
# App default screen + the active base screen; anything above is an overlay.
BASE_STACK_DEPTH: Final = 2


class AuthenticationRejected(Message):
    """A platform response rejected the stored user credential."""

    def __init__(self, credential_generation: int) -> None:
        super().__init__()
        self.credential_generation = credential_generation


def is_control_process() -> bool:
    """True when this process is the Control tab itself, not a launcher."""
    return (
        bool(os.environ.get(WEZTERM_PANE_ENV))
        and os.environ.get(CONTROL_PROCESS_ENV) == CONTROL_PROCESS_FLAG
    )


def mark_control_process() -> None:
    os.environ[CONTROL_PROCESS_ENV] = CONTROL_PROCESS_FLAG


def ensure_terminal_color() -> None:
    """Drop NO_COLOR so Textual keeps truecolor (room dots, chips, avatars).

    Launchers (CI, Cursor agent shells) often export NO_COLOR=1; WezTerm panes
    can inherit it and Textual then installs a Monochrome/NoColor filter.
    """
    os.environ.pop("NO_COLOR", None)
    if os.environ.get("FORCE_COLOR") == "0":
        os.environ.pop("FORCE_COLOR", None)
    os.environ.setdefault("COLORTERM", "truecolor")
    if os.environ.get("TERM") in (None, "", "dumb"):
        os.environ["TERM"] = "xterm-256color"


def name_control_tab() -> None:
    """Brand the disposable Band home tab and OS window (not python3.x)."""
    pane_id = current_pane_id()
    if pane_id is None:
        return
    with suppress(WezTermCliError, OSError):
        set_tab_title(pane_id, CONTROL_TAB_TITLE)
        set_window_title(pane_id, WINDOW_TITLE)


class ControlApp(App[None]):
    """A disposable Control view over the shared local agent runtime."""

    TITLE = WINDOW_TITLE

    SCREENS: ClassVar[dict[str, Callable[[], Screen[None]]]] = {
        SIGN_IN_SCREEN: SignInScreen,
        WORKSPACE_SCREEN: WorkspaceScreen,
        AGENTS_SCREEN: AgentsScreen,
        ROOMS_SCREEN: RoomsScreen,
        SETTINGS_SCREEN: SettingsScreen,
    }

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        host_auth: HostAuth | None = None,
        client: BandClient | None = None,
        starred: StarredRooms | None = None,
        managed_agents: ManagedAgentStore | None = None,
        preferences: PreferencesStore | None = None,
        opencode_server: OpenCodeServerManager | None = None,
        model_catalogs: ModelCatalogService | None = None,
        supervisor: SupervisorClient | None = None,
        initial_room_id: str | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings or load_settings()
        self.host_auth = host_auth or HostAuth(self.settings)
        self.client = client or BandClient(self.host_auth, self.settings)
        self.starred = starred or StarredRooms()
        self.managed_agents = managed_agents or ManagedAgentStore()
        self.preferences = preferences or PreferencesStore()
        self.opencode_server = opencode_server or OpenCodeServerManager()
        self.model_catalogs = model_catalogs or ModelCatalogService(
            self.opencode_server
        )
        self.supervisor = supervisor or SupervisorClient()
        self.client.set_authentication_rejected_handler(
            self._post_authentication_rejected
        )
        self.user_id: str | None = None
        self.agents_store = AgentsStore()
        self.rooms_store = RoomsStore()
        self._ending_session = False
        self._authentication_rejected_pending = False
        self.initial_room_id = initial_room_id

    def on_mount(self) -> None:
        name_control_tab()
        self.set_interval(PANE_POLL_SECONDS, self._reconcile_workers)
        if self.host_auth.has_stored_tokens():
            self.run_worker(self._restore_workspace(), group="workspace")
            return
        self.push_screen(SIGN_IN_SCREEN)

    async def on_unmount(self) -> None:
        """Closing one view never affects detached managed workers."""
        self.client.set_authentication_rejected_handler(None)
        await self.opencode_server.close()
        await self.client.aclose()

    async def _restore_workspace(self) -> None:
        """Restore a stored session or present a retryable sign-in gate."""
        try:
            await self.enter_workspace()
        except Exception as error:
            message = format_platform_error(error, operation="open workspace")
            self.notify(message, severity="error")
            self.push_screen(SIGN_IN_SCREEN)

    async def enter_workspace(self) -> None:
        """Identify the signed-in human, then open the shared workspace."""
        self.user_id = await self.client.whoami()
        await self.supervisor.connect(self.user_id)
        self.agents_store.replace_workers(await self.supervisor.list_workers())
        self.rooms_store.starred_ids = self.starred.list(self.user_id)
        announce_control_human(self.user_id)
        log_event("workspace entered", user_id=self.user_id)
        self._show(WORKSPACE_SCREEN)
        await self._open_initial_room()

    async def _open_initial_room(self) -> None:
        room_id = self.initial_room_id
        if room_id is None:
            return
        self.initial_room_id = None
        rooms = await self.client.list_my_chats()
        room = next((candidate for candidate in rooms if candidate.id == room_id), None)
        if room is None:
            self.notify("That Band room is unavailable.", severity="error")
            return
        self.open_room(room)

    # --- navigation ---------------------------------------------------------

    def action_show_agents(self) -> None:
        self._show(AGENTS_SCREEN)

    def action_show_rooms(self) -> None:
        self._show(ROOMS_SCREEN)

    def action_show_workspace(self) -> None:
        self._show(WORKSPACE_SCREEN)

    def action_show_settings(self) -> None:
        self.push_screen(SETTINGS_SCREEN)

    def action_sign_out(self) -> None:
        self.run_worker(self._sign_out(), group="auth")

    async def _sign_out(self) -> None:
        """An explicit sign-out stops the managed workers before clearing access."""
        if await self._return_to_sign_in(stop_workers=True):
            self.notify("Signed out.")

    def _post_authentication_rejected(self, credential_generation: int) -> None:
        self.post_message(AuthenticationRejected(credential_generation))

    def on_authentication_rejected(self, event: AuthenticationRejected) -> None:
        if event.credential_generation != self.host_auth.token_generation:
            log_event(
                "ignored stale authentication rejection",
                credential_generation=event.credential_generation,
                current_generation=self.host_auth.token_generation,
            )
            return
        if self._authentication_rejected_pending:
            return
        self._authentication_rejected_pending = True
        self.run_worker(self._handle_authentication_rejected(), group="auth")

    async def _handle_authentication_rejected(self) -> None:
        try:
            if await self._return_to_sign_in(stop_workers=False):
                self.notify(
                    "Your Band session expired. Sign in again.", severity="warning"
                )
        finally:
            self._authentication_rejected_pending = False

    async def _return_to_sign_in(self, *, stop_workers: bool) -> bool:
        """Clear a no-longer-valid session and show the sign-in gate."""
        if self._ending_session:
            return False
        self._ending_session = True
        try:
            stopped_agents = not stop_workers or await self._stop_managed_agents()
            if stop_workers and not stopped_agents:
                self.notify(
                    "Managed agents could not be stopped; sign-out was cancelled.",
                    severity="error",
                )
                return False
            await self.opencode_server.close()
            await self.host_auth.sign_out()
            self.user_id = None
            self.agents_store = AgentsStore()
            self.rooms_store = RoomsStore()
            while len(self.screen_stack) > 1:
                self.pop_screen()
            self.push_screen(SIGN_IN_SCREEN)
            return True
        finally:
            self._ending_session = False

    async def _stop_managed_agents(self) -> bool:
        """Request graceful shutdown for every worker in the shared runtime."""
        try:
            await self.supervisor.stop_all()
        except Exception as error:
            format_platform_error(error, operation="stop managed agents")
            return False
        self.agents_store.replace_workers(())
        return True

    async def _reconcile_workers(self) -> None:
        """Refresh this view from the supervisor; no pane is a lifecycle signal."""
        if self.user_id is None:
            return
        try:
            self.agents_store.replace_workers(await self.supervisor.list_workers())
        except Exception as error:
            self._report_worker_error(error)
            return
        self._refresh_agent_runtime_view()

    def _report_worker_error(self, error: BaseException) -> None:
        message = format_platform_error(error, operation="refresh managed agents")
        self.agents_store.set_status(AgentStatusSource.ACTION, message)
        self._refresh_agent_runtime_view()
        self.notify(message, severity="error")

    def _refresh_agent_runtime_view(self) -> None:
        match self.screen:
            case AgentsScreen() as screen:
                screen.mutate_reactive(AgentsScreen.store)
            case RoomDetailScreen() as screen:
                screen.mutate_reactive(RoomDetailScreen.store)

    def _show(self, screen_name: str) -> None:
        """Switch a view without losing its in-memory room draft."""
        while len(self.screen_stack) > BASE_STACK_DEPTH:
            self.pop_screen()
        if len(self.screen_stack) < BASE_STACK_DEPTH:
            self.push_screen(screen_name)
            return
        self.switch_screen(screen_name)

    def open_room(self, room: RoomRecord) -> None:
        self.rooms_store.enter_room(room.id)
        self.push_screen(RoomDetailScreen(room))

    # --- local state --------------------------------------------------------

    def toggle_star(self, room_id: str) -> None:
        if self.user_id is None:
            return
        self.starred.toggle(self.user_id, room_id)
        self.rooms_store.starred_ids = self.starred.list(self.user_id)

    def forget_room(self, room_id: str) -> None:
        """Drop a deleted room from the list and local star state."""
        if self.user_id is not None:
            self.starred.unstar(self.user_id, room_id)
            self.rooms_store.starred_ids = self.starred.list(self.user_id)
        self.rooms_store.remove_room(room_id)


def run_control_app(*, initial_room_id: str | None = None) -> int:
    """Run a disposable Band home or room view in this process."""
    mark_control_process()
    ensure_terminal_color()
    configure_diagnostics()
    ControlApp(initial_room_id=initial_room_id).run()
    return 0
