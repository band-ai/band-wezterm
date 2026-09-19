"""Control tab app — owns auth, the platform client, the window and screens.

The Control tab *is* the host: its process exiting shuts the host down and
stops every agent tab it started.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import suppress
from typing import ClassVar, Final

from textual.app import App
from textual.binding import Binding
from textual.screen import Screen

from band_wezterm.auth.host_auth import HostAuth
from band_wezterm.client import BandClient, RoomRecord
from band_wezterm.config import CONTROL_TAB_TITLE, Settings, load_settings
from band_wezterm.errors import format_platform_error
from band_wezterm.identity import AgentStatus, AvatarKind, agent_accent, initials
from band_wezterm.local_state import StarredRooms
from band_wezterm.managed_profiles import ManagedAgentStore
from band_wezterm.osc import OscKey, emit_many_to_stdout
from band_wezterm.preferences import PreferencesStore
from band_wezterm.tui.screens.agents import AgentsScreen
from band_wezterm.tui.screens.rooms import RoomDetailScreen, RoomsScreen
from band_wezterm.tui.screens.settings import SettingsScreen
from band_wezterm.tui.screens.sign_in import SignInScreen
from band_wezterm.tui.stores import AgentsStore, RoomsStore
from band_wezterm.wezterm_cli import (
    PaneId,
    WezTermCliError,
    WindowId,
    kill_pane,
    set_tab_title,
    window_id_for_pane,
)

CONTROL_PROCESS_ENV: Final = "BAND_WEZTERM_CONTROL"
CONTROL_PROCESS_FLAG: Final = "1"
WEZTERM_PANE_ENV: Final = "WEZTERM_PANE"

HOST_HUMAN_NAME: Final = "You"

SIGN_IN_SCREEN: Final = "sign_in"
AGENTS_SCREEN: Final = "agents"
ROOMS_SCREEN: Final = "rooms"
SETTINGS_SCREEN: Final = "settings"
# App default screen + the active base screen; anything above is an overlay.
BASE_STACK_DEPTH: Final = 2


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


def current_pane_id() -> PaneId | None:
    pane = os.environ.get(WEZTERM_PANE_ENV)
    if not pane:
        return None
    try:
        return PaneId(int(pane))
    except ValueError:
        return None


def current_window_id() -> WindowId | None:
    """Resolve the band window from the pane this process was spawned into."""
    pane_id = current_pane_id()
    if pane_id is None:
        return None
    try:
        return window_id_for_pane(pane_id)
    except Exception:
        return None


def name_control_tab() -> None:
    """Replace the process title (e.g. python3.14) with ``Control``."""
    pane_id = current_pane_id()
    if pane_id is None:
        return
    with suppress(WezTermCliError, OSError):
        set_tab_title(pane_id, CONTROL_TAB_TITLE)


class ControlApp(App[None]):
    """Single-window host UI: agents catalog and rooms, keyboard first."""

    TITLE = CONTROL_TAB_TITLE

    SCREENS: ClassVar[dict[str, Callable[[], Screen[None]]]] = {
        SIGN_IN_SCREEN: SignInScreen,
        AGENTS_SCREEN: AgentsScreen,
        ROOMS_SCREEN: RoomsScreen,
        SETTINGS_SCREEN: SettingsScreen,
    }

    BINDINGS: ClassVar[list[Binding]] = [
        # Ctrl+letter (not Ctrl+Shift): terminals collapse Shift on control
        # chords, so ctrl+shift+a never arrives. Avoid Ctrl+digit (macOS Spaces)
        # and F-keys (Fn). Ctrl+A/O are unbound in WezTerm defaults.
        Binding("ctrl+a", "show_agents", "Agents"),
        Binding("ctrl+o", "show_rooms", "Rooms"),
        Binding("f1", "show_agents", "Agents", show=False),
        Binding("f2", "show_rooms", "Rooms", show=False),
        Binding("ctrl+comma", "show_settings", "Settings"),
        Binding("ctrl+l", "sign_out", "Sign out"),
        Binding("ctrl+q", "quit", "Quit host"),
    ]

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        host_auth: HostAuth | None = None,
        client: BandClient | None = None,
        starred: StarredRooms | None = None,
        managed_agents: ManagedAgentStore | None = None,
        preferences: PreferencesStore | None = None,
    ) -> None:
        super().__init__()
        self.settings = settings or load_settings()
        self.host_auth = host_auth or HostAuth(self.settings)
        self.client = client or BandClient(self.host_auth, self.settings)
        self.starred = starred or StarredRooms()
        self.managed_agents = managed_agents or ManagedAgentStore()
        self.preferences = preferences or PreferencesStore()
        self.window_id = current_window_id()
        self.user_id: str | None = None
        self.agents_store = AgentsStore()
        self.rooms_store = RoomsStore()

    def on_mount(self) -> None:
        name_control_tab()
        if self.host_auth.has_stored_tokens():
            self.run_worker(self.enter_workspace(), group="workspace")
            return
        self.push_screen(SIGN_IN_SCREEN)

    async def on_unmount(self) -> None:
        """Host shutdown: every agent tab this host started goes with it."""
        for pane_id in list(self.agents_store.running.values()):
            with suppress(WezTermCliError, OSError):
                kill_pane(pane_id)
        self.agents_store.running.clear()
        await self.client.aclose()

    async def enter_workspace(self) -> None:
        """Identify the signed-in human, then open the agents catalog."""
        try:
            self.user_id = await self.client.whoami()
        except Exception as error:
            self.notify(format_platform_error(error), severity="error")
            return
        self.rooms_store.starred_ids = self.starred.list(self.user_id)
        announce_human(self.user_id)
        self._show(AGENTS_SCREEN)

    # --- navigation ---------------------------------------------------------

    def action_show_agents(self) -> None:
        self._show(AGENTS_SCREEN)

    def action_show_rooms(self) -> None:
        self._show(ROOMS_SCREEN)

    def action_show_settings(self) -> None:
        self.push_screen(SETTINGS_SCREEN)

    def action_sign_out(self) -> None:
        self.run_worker(self._sign_out(), group="auth")

    async def _sign_out(self) -> None:
        """Clear tokens, stop agent panes, return to Sign In."""
        for pane_id in list(self.agents_store.running.values()):
            with suppress(WezTermCliError, OSError):
                kill_pane(pane_id)
        self.agents_store.running.clear()
        await self.host_auth.sign_out()
        self.user_id = None
        self.agents_store = AgentsStore()
        self.rooms_store = RoomsStore()
        while len(self.screen_stack) > 1:
            self.pop_screen()
        self.push_screen(SIGN_IN_SCREEN)
        self.notify("Signed out.")

    def _show(self, screen_name: str) -> None:
        """Switching top-level screens discards any in-progress draft."""
        self.agents_store.discard_draft()
        self.rooms_store.discard_draft()
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


def announce_human(user_id: str) -> None:
    """The signed-in human stays online for as long as the host runs."""
    fields: dict[OscKey, str] = {
        OscKey.AGENT_ID: user_id,
        OscKey.AGENT_NAME: HOST_HUMAN_NAME,
        OscKey.AGENT_INITIALS: initials(HOST_HUMAN_NAME),
        OscKey.AGENT_COLOR: agent_accent(user_id),
        OscKey.AGENT_KIND: AvatarKind.HUMAN.value,
        OscKey.AGENT_STATUS: AgentStatus.ONLINE.value,
    }
    emit_many_to_stdout(fields)


def run_control_app() -> int:
    """Run the Control tab in this process; returns the host exit code."""
    mark_control_process()
    ensure_terminal_color()
    ControlApp().run()
    return 0
