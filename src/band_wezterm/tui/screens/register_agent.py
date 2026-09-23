"""Register / reconfigure agent wizard — one step, one field, then submit."""

from __future__ import annotations

import asyncio
from enum import StrEnum
from typing import ClassVar, Final

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

from band_wezterm.agent.adapters import HarnessUnavailableError
from band_wezterm.agent.readiness import preflight_managed_agent
from band_wezterm.agent_draft import (
    AgentDraft,
    agent_name_error,
    apply_draft_patch,
    create_default_draft,
    description_error,
    draft_from_profile,
    draft_name,
)
from band_wezterm.backends import (
    TUNING_DEFAULT_OPTION_ID,
    AgentTuning,
    TuningDimension,
    TuningDimensionId,
    list_backends,
    resolve_backend,
)
from band_wezterm.client import AgentRecord
from band_wezterm.diagnostics import log_event
from band_wezterm.errors import format_platform_error
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import profile_from_registration
from band_wezterm.roles import Role, list_roles
from band_wezterm.tui.screens import ControlScreen

NO_ROLE_ID: Final = "__no_role__"
KEEP_CURRENT_ROLE_ID: Final = "__keep_current_role__"
CUSTOM_TUNING_ID: Final = "__custom__"
DEFAULT_OPTION_ID: Final = "default"
REGISTER_CLEANUP_FAILED_MESSAGE: Final = "{error}; cleanup failed: {cleanup}"
OPEN_CLASS: Final = "open"


class WizardStep(StrEnum):
    HARNESS = "harness"
    ROLE = "role"
    NAME = "name"
    DESCRIPTION = "description"
    MODEL = "model"
    REASONING = "reasoning"


_TUNING_STEPS: Final[dict[TuningDimensionId, WizardStep]] = {
    TuningDimensionId.MODEL: WizardStep.MODEL,
    TuningDimensionId.REASONING: WizardStep.REASONING,
}

_TEXT_STEPS: Final[frozenset[WizardStep]] = frozenset(
    {WizardStep.NAME, WizardStep.DESCRIPTION}
)


class Id(StrEnum):
    TITLE = "register-title"
    HINT = "register-hint"
    OPTIONS = "register-options"
    TEXT = "register-text"
    STATUS = "register-status"


def selector(widget_id: Id) -> str:
    return f"#{widget_id.value}"


REGISTER_STEPS: Final[tuple[WizardStep, ...]] = (
    WizardStep.HARNESS,
    WizardStep.ROLE,
    WizardStep.NAME,
    WizardStep.DESCRIPTION,
)

RECONFIGURE_STEPS: Final[tuple[WizardStep, ...]] = (
    WizardStep.HARNESS,
    WizardStep.ROLE,
)


def _option_list_id(tuning_id: str) -> str:
    return DEFAULT_OPTION_ID if tuning_id == TUNING_DEFAULT_OPTION_ID else tuning_id


def _tuning_value(option_id: str) -> str:
    return TUNING_DEFAULT_OPTION_ID if option_id == DEFAULT_OPTION_ID else option_id


class RegisterAgentScreen(ControlScreen):
    """Create or reconfigure — reconfigure skips name/description (platform can't rename)."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "back", "Back"),
    ]

    DEFAULT_CSS = """
    RegisterAgentScreen #register-title {
        height: 1;
        padding: 0 1;
        text-style: bold;
    }
    RegisterAgentScreen #register-hint {
        height: 2;
        padding: 0 1;
        color: $text-muted;
    }
    RegisterAgentScreen #register-options {
        display: none;
        height: 12;
        border: round $accent;
    }
    RegisterAgentScreen #register-options.open {
        display: block;
    }
    RegisterAgentScreen #register-text {
        display: none;
    }
    RegisterAgentScreen #register-text.open {
        display: block;
    }
    RegisterAgentScreen #register-status {
        height: 1;
        padding: 0 1;
    }
    """

    def __init__(
        self,
        *,
        agent: AgentRecord | None = None,
        reconfigure: bool = False,
    ) -> None:
        super().__init__()
        self.reconfigure = reconfigure
        self.agent = agent
        self.draft: AgentDraft = create_default_draft()
        self.step: WizardStep = WizardStep.HARNESS
        self._roles: list[Role] = []
        self._keep_current_persona = reconfigure
        self._custom_dimension: TuningDimensionId | None = None
        self._catalog_errors: dict[HarnessId, str] = {}

    def compose(self) -> ComposeResult:
        heading = "Reconfigure agent" if self.reconfigure else "Register agent"
        yield Header()
        with Vertical():
            yield Label(heading, id=Id.TITLE.value)
            yield Static("", id=Id.HINT.value)
            yield OptionList(id=Id.OPTIONS.value)
            yield Input(id=Id.TEXT.value)
            yield Static("", id=Id.STATUS.value)
        yield Footer()

    def on_mount(self) -> None:
        self._roles = list_roles()
        if self.reconfigure and self.agent is not None:
            profile = self.control.managed_agents.get(self.agent.id)
            harness = (
                profile.harness
                if profile is not None
                else self.agent.harness or HarnessId.CLAUDE_SDK
            )
            self.draft = draft_from_profile(
                name=self.agent.name,
                harness=harness,
                persona=None if profile is None else profile.persona,
                tuning=AgentTuning() if profile is None else profile.tuning,
            )
        self._render_step()
        self._load_catalog(self.draft.harness)

    def action_back(self) -> None:
        if self._custom_dimension is not None:
            self._custom_dimension = None
            self._render_step()
            return
        steps = self._steps_for_draft()
        try:
            index = steps.index(self.step)
        except ValueError:
            self.app.pop_screen()
            return
        if index == 0:
            self.app.pop_screen()
            return
        self.step = steps[index - 1]
        self._render_step()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self._custom_dimension is not None or self.step in _TEXT_STEPS:
            return
        option_id = event.option.id
        if option_id is None:
            return
        self._accept_option(option_id)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        if self._custom_dimension is not None:
            self._accept_custom_tuning(value)
            return
        match self.step:
            case WizardStep.NAME:
                self._accept_name(value)
            case WizardStep.DESCRIPTION:
                self._accept_description(value)
            case _:
                return

    def _accept_name(self, value: str) -> None:
        error = agent_name_error(value)
        if error:
            self._set_status(error)
            return
        self.draft = apply_draft_patch(self.draft, name=value)
        self._advance()

    def _accept_description(self, value: str) -> None:
        error = description_error(value)
        if error:
            self._set_status(error)
            return
        self.draft = apply_draft_patch(self.draft, description=value)
        self._advance()

    def _accept_custom_tuning(self, value: str) -> None:
        dimension_id = self._custom_dimension
        if dimension_id is None:
            return
        dimension = self._dimension(dimension_id)
        if not value:
            self._set_status(f"{dimension.label} is required.")
            return
        self.draft = apply_draft_patch(
            self.draft,
            tuning=self.draft.tuning.with_dimension(dimension_id, value),
        )
        self._custom_dimension = None
        self._advance()

    def _accept_option(self, option_id: str) -> None:
        match self.step:
            case WizardStep.HARNESS:
                self.draft = apply_draft_patch(self.draft, harness=HarnessId(option_id))
                self._load_catalog(self.draft.harness)
            case WizardStep.ROLE:
                if not self._accept_role(option_id):
                    return
            case WizardStep.MODEL | WizardStep.REASONING:
                if not self._accept_tuning_option(option_id):
                    return
            case _:
                return
        self._advance()

    def _accept_role(self, option_id: str) -> bool:
        if option_id == KEEP_CURRENT_ROLE_ID:
            self._keep_current_persona = True
            return True
        self._keep_current_persona = False
        if option_id == NO_ROLE_ID:
            self.draft = apply_draft_patch(self.draft, role=None)
            return True
        role = next((item for item in self._roles if item.id == option_id), None)
        if role is None:
            self._set_status("That role is no longer in the library.")
            return False
        self.draft = apply_draft_patch(self.draft, role=role)
        return True

    def _accept_tuning_option(self, option_id: str) -> bool:
        dimension_id = self._step_dimension()
        if dimension_id is None:
            return False
        if option_id == CUSTOM_TUNING_ID:
            self._custom_dimension = dimension_id
            self._render_step()
            return False
        self.draft = apply_draft_patch(
            self.draft,
            tuning=self.draft.tuning.with_dimension(
                dimension_id, _tuning_value(option_id)
            ),
        )
        return True

    def _steps_for_draft(self) -> tuple[WizardStep, ...]:
        base = RECONFIGURE_STEPS if self.reconfigure else REGISTER_STEPS
        extra = tuple(
            _TUNING_STEPS[dimension.id]
            for dimension in resolve_backend(self.draft.harness).tuning
            if dimension.id in _TUNING_STEPS
        )
        return (*base, *extra)

    def _advance(self) -> None:
        steps = self._steps_for_draft()
        try:
            index = steps.index(self.step)
        except ValueError:
            self._set_status("Wizard step is out of range.")
            return
        next_index = index + 1
        if next_index >= len(steps):
            self._submit()
            return
        self.step = steps[next_index]
        self._render_step()

    def _verb(self) -> str:
        return "Reconfigure" if self.reconfigure else "Register"

    def _dimension(self, dimension_id: TuningDimensionId) -> TuningDimension:
        backend = resolve_backend(self.draft.harness)
        fallback = next(dim for dim in backend.tuning if dim.id is dimension_id)
        catalog = self.control.model_catalogs.get(self.draft.harness)
        if catalog is None:
            return fallback
        return catalog.dimension(
            fallback,
            selected_model=self.draft.tuning.value_for(TuningDimensionId.MODEL),
        )

    def _step_dimension(self) -> TuningDimensionId | None:
        match self.step:
            case WizardStep.MODEL:
                return TuningDimensionId.MODEL
            case WizardStep.REASONING:
                return TuningDimensionId.REASONING
            case _:
                return None

    def _render_step(self) -> None:
        self._set_status("")
        verb = self._verb()
        if self._custom_dimension is not None:
            dimension = self._dimension(self._custom_dimension)
            self._show_text(
                title=f"{verb} agent — custom {dimension.label.lower()}",
                hint=f"Enter a {dimension.label.lower()} this runtime accepts",
                value=self._custom_prefill(dimension),
                placeholder=dimension.label.lower(),
            )
            return
        match self.step:
            case WizardStep.HARNESS:
                self._show_choices(
                    title=f"{verb} agent — runtime",
                    hint="Which agent runtime should run locally?",
                    items=[
                        (f"{backend.label}  ({backend.badge})", backend.harness.value)
                        for backend in list_backends()
                    ],
                    selected_id=self.draft.harness.value,
                )
            case WizardStep.ROLE:
                self._show_choices(
                    title=f"{verb} agent — role",
                    hint="Give the agent a role? (from ~/.band/roles)",
                    items=self._role_choices(),
                    selected_id=self._selected_role_id(),
                )
            case WizardStep.NAME:
                self._show_text(
                    title=f"{verb} agent — name",
                    hint="Agent name",
                    value=draft_name(self.draft),
                    placeholder="Agent name",
                )
            case WizardStep.DESCRIPTION:
                self._show_text(
                    title=f"{verb} agent — description",
                    hint="What this agent does (platform requires ≥10 chars)",
                    value=self.draft.description,
                    placeholder="What this agent does",
                )
            case WizardStep.MODEL | WizardStep.REASONING:
                dimension_id = self._step_dimension()
                if dimension_id is None:
                    return
                dimension = self._dimension(dimension_id)
                self._show_choices(
                    title=f"{verb} agent — {dimension.label.lower()}",
                    hint=dimension.label,
                    items=self._tuning_choices(dimension),
                    selected_id=self._selected_tuning_id(dimension),
                )
                if error := self._catalog_errors.get(self.draft.harness):
                    self._set_status(error)

    @work(exclusive=True, group="model-catalog")
    async def _load_catalog(self, harness: HarnessId) -> None:
        try:
            catalog = await self.control.model_catalogs.load(harness)
        except Exception as error:
            message = format_platform_error(error, operation="load model catalog")
            self._catalog_errors[harness] = (
                f"{message} Showing adapter defaults and Custom instead."
            )
            log_event(
                "model catalog load failed",
                harness=harness.value,
                error=repr(error),
            )
        else:
            self._catalog_errors.pop(harness, None)
            log_event(
                "model catalog loaded",
                harness=harness.value,
                models=len(catalog.models),
            )
        if harness is self.draft.harness and self._step_dimension() is not None:
            self._render_step()

    def _role_choices(self) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        if self.reconfigure:
            items.append(("Keep current role", KEEP_CURRENT_ROLE_ID))
        items.append(("No specific role", NO_ROLE_ID))
        for role in self._roles:
            detail = f" — {role.description}" if role.description else ""
            items.append((f"{role.label}{detail}", role.id))
        return items

    def _selected_role_id(self) -> str:
        if self.reconfigure and self._keep_current_persona:
            return KEEP_CURRENT_ROLE_ID
        if self.draft.role is None:
            return NO_ROLE_ID
        return self.draft.role.id or NO_ROLE_ID

    def _tuning_choices(self, dimension: TuningDimension) -> list[tuple[str, str]]:
        items: list[tuple[str, str]] = []
        for option in dimension.options:
            label = option.label
            if option.description:
                label = f"{label} — {option.description}"
            items.append((label, _option_list_id(option.id)))
        if dimension.allow_custom:
            items.append(("Custom…", CUSTOM_TUNING_ID))
        return items

    def _selected_tuning_id(self, dimension: TuningDimension) -> str:
        current = self.draft.tuning.value_for(dimension.id) or TUNING_DEFAULT_OPTION_ID
        known = {option.id for option in dimension.options}
        if current not in known and dimension.allow_custom:
            return CUSTOM_TUNING_ID
        return _option_list_id(current)

    def _custom_prefill(self, dimension: TuningDimension) -> str:
        current = self.draft.tuning.value_for(dimension.id) or ""
        known = {option.id for option in dimension.options}
        return "" if current in known else current

    def _show_choices(
        self,
        *,
        title: str,
        hint: str,
        items: list[tuple[str, str]],
        selected_id: str,
    ) -> None:
        self.query_one(selector(Id.TITLE), Label).update(title)
        self.query_one(selector(Id.HINT), Static).update(hint)
        options = self.query_one(selector(Id.OPTIONS), OptionList)
        text = self.query_one(selector(Id.TEXT), Input)
        text.remove_class(OPEN_CLASS)
        text.value = ""
        options.add_class(OPEN_CLASS)
        options.clear_options()
        highlight = 0
        for index, (label, option_id) in enumerate(items):
            options.add_option(Option(label, id=option_id))
            if option_id == selected_id:
                highlight = index
        if options.option_count:
            options.highlighted = highlight
        options.focus()

    def _show_text(
        self, *, title: str, hint: str, value: str, placeholder: str
    ) -> None:
        self.query_one(selector(Id.TITLE), Label).update(title)
        self.query_one(selector(Id.HINT), Static).update(hint)
        options = self.query_one(selector(Id.OPTIONS), OptionList)
        text = self.query_one(selector(Id.TEXT), Input)
        options.remove_class(OPEN_CLASS)
        options.clear_options()
        text.add_class(OPEN_CLASS)
        text.value = value
        text.placeholder = placeholder
        text.focus()

    def _draft_blocking_error(self) -> tuple[WizardStep, str] | None:
        if self.reconfigure:
            return None
        name_error = agent_name_error(draft_name(self.draft))
        if name_error:
            return WizardStep.NAME, name_error
        desc_error = description_error(self.draft.description)
        if desc_error:
            return WizardStep.DESCRIPTION, desc_error
        return None

    def _go_to(self, step: WizardStep, status: str = "") -> None:
        self.step = step
        self._custom_dimension = None
        self._render_step()
        if status:
            self._set_status(status)

    @work(exclusive=True, group="agents-register")
    async def _submit(self) -> None:
        blocking = self._draft_blocking_error()
        if blocking is not None:
            self._go_to(*blocking)
            return
        if self.reconfigure:
            self._submit_reconfigure()
            return
        draft = self.draft
        if not await self._preflight_draft(draft.harness):
            return
        name = draft_name(draft)
        try:
            agent = await self.control.client.create_agent(
                name=name, description=draft.description
            )
        except Exception as error:
            message = format_platform_error(error, operation="register agent")
            if message.startswith("Name "):
                self._go_to(WizardStep.NAME, message)
                return
            self._set_status(message)
            return
        persona = draft.role.content if draft.role is not None else None
        try:
            self.control.managed_agents.record(
                profile_from_registration(
                    agent_id=agent.id,
                    name=agent.name,
                    harness=draft.harness,
                    persona=persona,
                    tuning=draft.tuning,
                )
            )
        except Exception as error:
            try:
                await self.control.client.delete_agent(agent.id)
            except Exception as cleanup_error:
                self._set_status(
                    REGISTER_CLEANUP_FAILED_MESSAGE.format(
                        error=format_platform_error(error, operation="save profile"),
                        cleanup=format_platform_error(
                            cleanup_error, operation="clean up registration"
                        ),
                    )
                )
                return
            self._set_status(format_platform_error(error, operation="save profile"))
            return
        managed_agent = agent.model_copy(update={"harness": draft.harness})
        self.control.agents_store.add_agent(managed_agent)
        self.control.agents_store.status = (
            f"Registered {agent.name} ({draft.harness.value}) — not started."
        )
        log_event(
            "registered agent",
            agent_id=agent.id,
            harness=draft.harness.value,
            has_persona=persona is not None,
            model=draft.tuning.model or "default",
            reasoning=draft.tuning.reasoning or "default",
        )
        self.app.pop_screen()

    @work(exclusive=True, group="agents-reconfigure")
    async def _submit_reconfigure(self) -> None:
        agent = self.agent
        if agent is None:
            self._set_status("No agent to reconfigure.")
            return
        draft = self.draft
        if not await self._preflight_draft(draft.harness):
            return
        previous = self.control.managed_agents.get(agent.id)
        persona = (
            previous.persona
            if self._keep_current_persona and previous is not None
            else (draft.role.content if draft.role is not None else None)
        )
        next_profile = profile_from_registration(
            agent_id=agent.id,
            name=agent.name,
            harness=draft.harness,
            persona=persona,
            tuning=draft.tuning,
        )
        try:
            self.control.managed_agents.record(next_profile)
        except Exception as error:
            self._set_status(
                format_platform_error(error, operation="reconfigure agent")
            )
            return
        updated = agent.model_copy(update={"harness": draft.harness})
        self.control.agents_store.update_agent(updated)
        self.control.agents_store.status = (
            f"Reconfigured {agent.name} ({draft.harness.value}) — restart to apply."
        )
        log_event(
            "reconfigured agent",
            agent_id=agent.id,
            harness=draft.harness.value,
            has_persona=persona is not None,
            model=draft.tuning.model or "default",
            reasoning=draft.tuning.reasoning or "default",
        )
        self.app.pop_screen()

    async def _preflight_draft(self, harness: HarnessId) -> bool:
        try:
            await asyncio.to_thread(preflight_managed_agent, harness)
        except HarnessUnavailableError as error:
            self._set_status(str(error))
            return False
        return True

    def _set_status(self, status: str) -> None:
        self.query_one(selector(Id.STATUS), Static).update(status)
