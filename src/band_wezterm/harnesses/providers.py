"""Built-in harness providers; add a new harness here and register it once."""

from __future__ import annotations

from typing import Any, Final

from band_wezterm.agent.opencode_server import OpenCodeServerManager
from band_wezterm.catalogs.models import HarnessCatalog
from band_wezterm.catalogs.providers import (
    CLAUDE_MODEL_OPTIONS,
    load_claude_catalog,
    load_codex_catalog,
    load_copilot_catalog,
    load_opencode_catalog,
)
from band_wezterm.harnesses.base import (
    AdapterRequest,
    HarnessProvider,
    HarnessUnavailableError,
)
from band_wezterm.harnesses.models import (
    TUNING_DEFAULT_OPTION_ID,
    AgentTuning,
    HarnessBackend,
    TuningDimension,
    TuningDimensionId,
    TuningOption,
)
from band_wezterm.identity import HarnessId

_DEFAULT = TuningOption(id=TUNING_DEFAULT_OPTION_ID, label="Adapter default")
_CATALOG_FALLBACK: Final = (_DEFAULT,)
_CLAUDE_MODEL_FALLBACKS: Final = (_DEFAULT, *CLAUDE_MODEL_OPTIONS)

_SDK_EXTRAS: Final = {
    HarnessId.CLAUDE_SDK: ("claude_sdk", "claude-sdk"),
    HarnessId.CODEX: ("codex", "codex"),
    HarnessId.COPILOT_SDK: ("copilot_sdk", "copilot-sdk"),
    HarnessId.OPENCODE: ("opencode", "opencode"),
}


def _missing(harness: HarnessId, error: ImportError) -> HarnessUnavailableError:
    host_extra, sdk_extra = _SDK_EXTRAS[harness]
    return HarnessUnavailableError(
        f"Harness {harness.value} requires `uv sync --extra {host_extra}` "
        f"(or `--extra agents`; installs band-sdk[{sdk_extra}]). "
        f"Import failed: {error}"
    )


def _apply_persona(kwargs: dict[str, Any], persona: str | None) -> None:
    if persona:
        kwargs["custom_section"] = persona


def _apply_reasoning(
    kwargs: dict[str, Any], tuning: AgentTuning, *, kwarg: str = "reasoning_effort"
) -> None:
    effort = tuning.value_for(TuningDimensionId.REASONING)
    if effort is not None:
        kwargs[kwarg] = effort


class ClaudeHarness(HarnessProvider):
    backend = HarnessBackend(
        harness=HarnessId.CLAUDE_SDK,
        label="Claude",
        badge="CL",
        tuning=(
            TuningDimension(
                id=TuningDimensionId.MODEL,
                label="Model",
                options=_CLAUDE_MODEL_FALLBACKS,
                allow_custom=True,
            ),
            TuningDimension(
                id=TuningDimensionId.REASONING,
                label="Effort",
                options=_CATALOG_FALLBACK,
                allow_custom=True,
            ),
        ),
    )
    aliases = (HarnessId.CLAUDE,)

    def build_adapter(self, request: AdapterRequest) -> object:
        try:
            from band.adapters import ClaudeSDKAdapter  # noqa: PLC0415
        except ImportError as error:
            raise _missing(self.id, error) from error
        kwargs: dict[str, Any] = {"cwd": str(request.cwd) if request.cwd else None}
        if model := request.tuning.value_for(TuningDimensionId.MODEL):
            kwargs["model"] = model
        _apply_reasoning(kwargs, request.tuning, kwarg="effort")
        _apply_persona(kwargs, request.persona)
        return ClaudeSDKAdapter(**kwargs)

    async def load_catalog(self, server: OpenCodeServerManager) -> HarnessCatalog:
        del server
        return await load_claude_catalog()


class CodexHarness(HarnessProvider):
    backend = HarnessBackend(
        harness=HarnessId.CODEX,
        label="Codex",
        badge="CX",
        tuning=tuple(
            TuningDimension(
                id=dimension,
                label=label,
                options=_CATALOG_FALLBACK,
                allow_custom=True,
            )
            for dimension, label in (
                (TuningDimensionId.MODEL, "Model"),
                (TuningDimensionId.REASONING, "Reasoning effort"),
            )
        ),
    )

    def build_adapter(self, request: AdapterRequest) -> object:
        try:
            from band.adapters import CodexAdapter  # noqa: PLC0415
            from band.adapters.codex import CodexAdapterConfig  # noqa: PLC0415
        except ImportError as error:
            raise _missing(self.id, error) from error
        kwargs: dict[str, Any] = {}
        if request.cwd is not None:
            # band-sdk defaults each room to an empty <cwd>/.band-workspaces/<room>;
            # pin rooms to the launch dir so Codex works on the user's project.
            # band-sdk rejects a second concurrent room sharing this workspace.
            workspace = str(request.cwd.resolve())
            kwargs["workspace_for_room"] = lambda _room_id: workspace
        if model := request.tuning.value_for(TuningDimensionId.MODEL):
            kwargs["model"] = model
        _apply_reasoning(kwargs, request.tuning)
        _apply_persona(kwargs, request.persona)
        return CodexAdapter(CodexAdapterConfig(**kwargs))

    async def load_catalog(self, server: OpenCodeServerManager) -> HarnessCatalog:
        del server
        return await load_codex_catalog()


class CopilotHarness(HarnessProvider):
    backend = HarnessBackend(
        harness=HarnessId.COPILOT_SDK,
        label="Copilot",
        badge="CP",
        tuning=tuple(
            TuningDimension(
                id=dimension,
                label=label,
                options=_CATALOG_FALLBACK,
                allow_custom=True,
            )
            for dimension, label in (
                (TuningDimensionId.MODEL, "Model"),
                (TuningDimensionId.REASONING, "Reasoning effort"),
            )
        ),
    )
    aliases = (HarnessId.COPILOT,)

    def build_adapter(self, request: AdapterRequest) -> object:
        try:
            from band.adapters import CopilotSDKAdapter  # noqa: PLC0415
            from band.adapters.copilot_sdk import (  # noqa: PLC0415
                CopilotSDKAdapterConfig,
            )
        except ImportError as error:
            raise _missing(self.id, error) from error
        kwargs: dict[str, Any] = {}
        if model := request.tuning.value_for(TuningDimensionId.MODEL):
            kwargs["model"] = model
        _apply_reasoning(kwargs, request.tuning)
        _apply_persona(kwargs, request.persona)
        return CopilotSDKAdapter(CopilotSDKAdapterConfig(**kwargs))

    async def load_catalog(self, server: OpenCodeServerManager) -> HarnessCatalog:
        del server
        return await load_copilot_catalog()


class OpenCodeHarness(HarnessProvider):
    backend = HarnessBackend(
        harness=HarnessId.OPENCODE,
        label="OpenCode",
        badge="OM",
        tuning=(
            TuningDimension(
                id=TuningDimensionId.MODEL,
                label="Model id",
                options=_CATALOG_FALLBACK,
                allow_custom=True,
            ),
            TuningDimension(
                id=TuningDimensionId.REASONING,
                label="Variant / effort",
                options=_CATALOG_FALLBACK,
                allow_custom=True,
            ),
        ),
    )
    aliases = (HarnessId.OMP,)

    def build_adapter(self, request: AdapterRequest) -> object:
        try:
            from band.adapters import OpencodeAdapter  # noqa: PLC0415
            from band.adapters.opencode.config import (  # noqa: PLC0415
                OpencodeAdapterConfig,
            )
        except ImportError as error:
            raise _missing(self.id, error) from error
        kwargs: dict[str, Any] = {}
        if request.cwd is not None:
            kwargs["directory"] = str(request.cwd)
        if request.opencode_server_url is not None:
            kwargs["base_url"] = request.opencode_server_url
        if model := request.tuning.value_for(TuningDimensionId.MODEL):
            provider_id, separator, model_id = model.partition("/")
            kwargs.update(
                {"provider_id": provider_id, "model_id": model_id}
                if separator
                else {"model_id": model}
            )
        if variant := request.tuning.value_for(TuningDimensionId.REASONING):
            kwargs["variant"] = variant
        _apply_persona(kwargs, request.persona)
        return OpencodeAdapter(OpencodeAdapterConfig(**kwargs))

    async def load_catalog(self, server: OpenCodeServerManager) -> HarnessCatalog:
        return await load_opencode_catalog(server)


BUILTIN_HARNESSES: Final[tuple[HarnessProvider, ...]] = (
    ClaudeHarness(),
    CodexHarness(),
    CopilotHarness(),
    OpenCodeHarness(),
)
