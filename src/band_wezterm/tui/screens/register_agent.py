"""Multi-step register / reconfigure agent wizard (VSC parity)."""

from __future__ import annotations

from enum import StrEnum
from typing import ClassVar, Final

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.widgets import Footer, Header, Input, Label, OptionList, Static
from textual.widgets.option_list import Option

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
    TuningDimensionId,
    list_backends,
    resolve_backend,
)
from band_wezterm.client import AgentRecord
from band_wezterm.errors import format_platform_error
from band_wezterm.identity import HarnessId
from band_wezterm.managed_profiles import profile_from_registration
from band_wezterm.roles import Role, list_roles
from band_wezterm.tui.screens import ControlScreen

NO_ROLE_ID: Final = ""
CUSTOM_MODEL_SENTINEL: Final = "__custom__"
OPEN_CLASS: Final = "open"


class WizardStep(StrEnum):
    HARNESS = "harness"
    ROLE = "role"
    NAME = "name"
    DESCRIPTION = "description"
    MODEL = "model"
    REASONING = "reasoning"
    CUSTOM_MODEL = "custom_model"


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


class RegisterAgentScreen(ControlScreen):
    """Create or reconfigure — reconfigure skips name/description (platform can't rename)."""

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("escape", "cancel", "Cancel", show=False),
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
        height: 12;
        border: round $accent;
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

    def action_cancel(self) -> None:
        self.app.pop_screen()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self.step in {WizardStep.NAME, WizardStep.DESCRIPTION, WizardStep.CUSTOM_MODEL}:
            return
        option_id = event.option.id
        if option_id is None:
            return
        self._accept_option(str(option_id))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        value = event.value.strip()
        match self.step:
            case WizardStep.NAME:
                error = agent_name_error(value)
                if error:
                    self._set_status(error)
                    return
                self.draft = apply_draft_patch(self.draft, name=value)
                self._advance()
            case WizardStep.DESCRIPTION:
                error = description_error(value)
                if error:
                    self._set_status(error)
                    return
                self.draft = apply_draft_patch(self.draft, description=value)
                self._advance()
            case WizardStep.CUSTOM_MODEL:
                if not value:
                    self._set_status("Model id is required.")
                    return
                self.draft = apply_draft_patch(
                    self.draft,
                    tuning=self.draft.tuning.with_dimension(TuningDimensionId.MODEL, value),
                )
                self._advance()

    def _accept_option(self, option_id: str) -> None:
        match self.step:
            case WizardStep.HARNESS:
                self.draft = apply_draft_patch(self.draft, harness=HarnessId(option_id))
            case WizardStep.ROLE:
                if option_id == NO_ROLE_ID:
                    self.draft = apply_draft_patch(self.draft, role=None)
                else:
                    role = next(role for role in self._roles if role.id == option_id)
                    self.draft = apply_draft_patch(self.draft, role=role)
            case WizardStep.MODEL:
                if option_id == CUSTOM_MODEL_SENTINEL:
                    self.step = WizardStep.CUSTOM_MODEL
                    self._render_step()
                    return
                model_value = (
                    TUNING_DEFAULT_OPTION_ID if option_id == "default" else option_id
                )
                self.draft = apply_draft_patch(
                    self.draft,
                    tuning=self.draft.tuning.with_dimension(
                        TuningDimensionId.MODEL, model_value
                    ),
                )
            case WizardStep.REASONING:
                reasoning_value = (
                    TUNING_DEFAULT_OPTION_ID if option_id == "default" else option_id
                )
                self.draft = apply_draft_patch(
                    self.draft,
                    tuning=self.draft.tuning.with_dimension(
                        TuningDimensionId.REASONING, reasoning_value
                    ),
                )
            case _:
                return
        self._advance()

    def _steps_for_draft(self) -> tuple[WizardStep, ...]:
        backend = resolve_backend(self.draft.harness)
        base = RECONFIGURE_STEPS if self.reconfigure else REGISTER_STEPS
        steps: list[WizardStep] = list(base)
        dimension_ids = {dimension.id for dimension in backend.tuning}
        if TuningDimensionId.MODEL in dimension_ids:
            steps.append(WizardStep.MODEL)
        if TuningDimensionId.REASONING in dimension_ids:
            steps.append(WizardStep.REASONING)
        return tuple(steps)

    def _advance(self) -> None:
        steps = self._steps_for_draft()
        try:
            index = steps.index(self.step)
        except ValueError:
            index = steps.index(WizardStep.MODEL)
        next_index = index + 1
        if next_index >= len(steps):
            self._submit()
            return
        self.step = steps[next_index]
        self._render_step()

    def _verb(self) -> str:
        return "Reconfigure" if self.reconfigure else "Register"

    def _render_step(self) -> None:
        title = self.query_one(selector(Id.TITLE), Label)
        hint = self.query_one(selector(Id.HINT), Static)
        options = self.query_one(selector(Id.OPTIONS), OptionList)
        text = self.query_one(selector(Id.TEXT), Input)
        self._set_status("")
        options.clear_options()
        text.remove_class(OPEN_CLASS)
        text.value = ""
        verb = self._verb()
        match self.step:
            case WizardStep.HARNESS:
                title.update(f"{verb} agent — runtime")
                hint.update("Which agent runtime should run locally?")
                for backend in list_backends():
                    options.add_option(
                        Option(
                            f"{backend.label}  ({backend.badge})",
                            id=backend.harness.value,
                        )
                    )
                options.focus()
            case WizardStep.ROLE:
                title.update(f"{verb} agent — role")
                hint.update("Give the agent a role? (from ~/.band/roles)")
                options.add_option(Option("No specific role", id=NO_ROLE_ID))
                for role in self._roles:
                    detail = f" — {role.description}" if role.description else ""
                    options.add_option(Option(f"{role.label}{detail}", id=role.id))
                options.focus()
            case WizardStep.NAME:
                title.update(f"{verb} agent — name")
                hint.update("Agent name")
                text.add_class(OPEN_CLASS)
                text.value = draft_name(self.draft)
                text.placeholder = "Agent name"
                text.focus()
            case WizardStep.DESCRIPTION:
                title.update(f"{verb} agent — description")
                hint.update("What this agent does (platform requires ≥10 chars)")
                text.add_class(OPEN_CLASS)
                text.value = self.draft.description
                text.placeholder = "What this agent does"
                text.focus()
            case WizardStep.MODEL:
                title.update(f"{verb} agent — model")
                hint.update("Model for this runtime (Enter to accept)")
                backend = resolve_backend(self.draft.harness)
                model_dim = next(
                    dim for dim in backend.tuning if dim.id is TuningDimensionId.MODEL
                )
                for option in model_dim.options:
                    label = option.label
                    if option.description:
                        label = f"{label} — {option.description}"
                    options.add_option(Option(label, id=option.id or "default"))
                if model_dim.allow_custom:
                    options.add_option(Option("Custom model id…", id=CUSTOM_MODEL_SENTINEL))
                options.focus()
            case WizardStep.CUSTOM_MODEL:
                title.update(f"{verb} agent — custom model")
                hint.update("Enter a model id this runtime accepts")
                text.add_class(OPEN_CLASS)
                text.placeholder = "model id"
                text.focus()
            case WizardStep.REASONING:
                title.update(f"{verb} agent — reasoning")
                hint.update("Reasoning / thinking control")
                backend = resolve_backend(self.draft.harness)
                reasoning_dim = next(
                    dim for dim in backend.tuning if dim.id is TuningDimensionId.REASONING
                )
                for option in reasoning_dim.options:
                    options.add_option(Option(option.label, id=option.id or "default"))
                options.focus()

    @work(exclusive=True, group="agents-register")
    async def _submit(self) -> None:
        if self.reconfigure:
            self._submit_reconfigure()
            return
        draft = self.draft
        name = draft_name(draft)
        try:
            agent = await self.control.client.create_agent(
                name=name,
                description=draft.description,
                harness=draft.harness,
            )
        except Exception as error:
            self._set_status(format_platform_error(error))
            return
        persona = draft.role.content if draft.role is not None else None
        self.control.managed_agents.record(
            profile_from_registration(
                agent_id=agent.id,
                name=agent.name,
                harness=draft.harness,
                persona=persona,
                tuning=draft.tuning,
            )
        )
        self.control.agents_store.add_agent(agent)
        self.control.agents_store.status = (
            f"Registered {agent.name} ({draft.harness.value}) — not started."
        )
        self.app.pop_screen()

    def _submit_reconfigure(self) -> None:
        agent = self.agent
        if agent is None:
            self._set_status("No agent to reconfigure.")
            return
        draft = self.draft
        persona = draft.role.content if draft.role is not None else None
        previous = self.control.managed_agents.get(agent.id)
        next_profile = profile_from_registration(
            agent_id=agent.id,
            name=agent.name,
            harness=draft.harness,
            persona=persona,
            tuning=draft.tuning,
        )
        # Profile first so Start's prefer-profile path cannot see keyring ahead
        # of durable local state if the keyring write fails afterward.
        self.control.managed_agents.record(next_profile)
        try:
            self.control.client.update_managed_harness(agent.id, draft.harness)
        except Exception as error:
            if previous is None:
                self.control.managed_agents.remove(agent.id)
            else:
                self.control.managed_agents.record(previous)
            self._set_status(str(error))
            return
        updated = agent.model_copy(update={"harness": draft.harness})
        self.control.agents_store.update_agent(updated)
        self.control.agents_store.status = (
            f"Reconfigured {agent.name} ({draft.harness.value}) — restart to apply."
        )
        self.app.pop_screen()

    def _set_status(self, status: str) -> None:
        self.query_one(selector(Id.STATUS), Static).update(status)
