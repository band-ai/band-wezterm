"""Agent/human visual identity — direct hash port of identityVisuals.ts."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from functools import lru_cache
from typing import Final
from uuid import UUID


class AvatarKind(StrEnum):
    HUMAN = "human"
    AGENT = "agent"


class HarnessId(StrEnum):
    """Adapter / backend ids — SDK names plus extension aliases."""

    CLAUDE = "claude"
    CLAUDE_SDK = "claude_sdk"
    CODEX = "codex"
    COPILOT = "copilot"
    COPILOT_SDK = "copilot_sdk"
    OMP = "omp"
    OPENCODE = "opencode"


class HarnessBadge(StrEnum):
    """Two-letter tab/avatar badge letters (extension media/badges parity)."""

    CL = "CL"
    CX = "CX"
    CP = "CP"
    OM = "OM"


class AgentStatus(StrEnum):
    """Avatar presence dot — correction #2 (`AvatarStatus`)."""

    ONLINE = "online"
    OFFLINE = "offline"


class AgentRuntime(StrEnum):
    """Local process state — correction #2 (`AgentRuntimeStatus`)."""

    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    IDLE = "idle"
    ERROR = "error"


HUE_BUCKET_COUNT: Final = 16
RESERVED_HUE_BANDS: Final[tuple[tuple[float, float], ...]] = (
    (0.0, 20.0),
    (100.0, 150.0),
)
TONE_VARIANTS: Final[tuple[tuple[float, float], ...]] = (
    (0.5, 0.4),
    (0.58, 0.46),
    (0.65, 0.52),
)

# Correction #9: SDK adapter `opencode` ↔ extension badge `OM`.
HARNESS_BADGES: Final[Mapping[HarnessId, HarnessBadge]] = {
    HarnessId.CLAUDE: HarnessBadge.CL,
    HarnessId.CLAUDE_SDK: HarnessBadge.CL,
    HarnessId.CODEX: HarnessBadge.CX,
    HarnessId.COPILOT: HarnessBadge.CP,
    HarnessId.COPILOT_SDK: HarnessBadge.CP,
    HarnessId.OMP: HarnessBadge.OM,
    HarnessId.OPENCODE: HarnessBadge.OM,
}


def hash_string(value: str) -> int:
    """djb2 — same algorithm as identityVisuals.ts `hashString`."""
    digest = 5381
    for char in value:
        digest = ((digest * 33) ^ ord(char)) & 0xFFFFFFFF
    return digest


def _allowed_hues() -> tuple[float, ...]:
    step = 360.0 / HUE_BUCKET_COUNT
    hues: list[float] = []
    for bucket in range(HUE_BUCKET_COUNT):
        hue = bucket * step
        if any(start <= hue < end for start, end in RESERVED_HUE_BANDS):
            continue
        hues.append(hue)
    return tuple(hues)


ALLOWED_HUES: Final = _allowed_hues()


def _avatar_hue(identity_id: str) -> float:
    return ALLOWED_HUES[hash_string(identity_id) % len(ALLOWED_HUES)]


def _avatar_tone(identity_id: str) -> tuple[float, float]:
    return TONE_VARIANTS[hash_string(f"{identity_id}|tone") % len(TONE_VARIANTS)]


def _hsl_to_hex(hue: float, saturation: float, lightness: float) -> str:
    chroma = saturation * min(lightness, 1.0 - lightness)

    def channel(n: float) -> str:
        k = (n + hue / 30.0) % 12.0
        value = lightness - chroma * max(-1.0, min(k - 3.0, 9.0 - k, 1.0))
        return f"{round(255 * value):02x}"

    return f"#{channel(0)}{channel(8)}{channel(4)}"


def initials(display_name: str) -> str:
    words = [part for part in display_name.strip().split() if part]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[-1][0]).upper()


@lru_cache(maxsize=512)
def agent_accent(agent_id: UUID | str) -> str:
    """Deterministic accent hex from id — identityVisuals.ts colorHex port.

    Ready to swap to platform avatar_url `c`/`l` hints once band_rest exposes them.
    """
    identity_id = str(agent_id)
    saturation, lightness = _avatar_tone(identity_id)
    return _hsl_to_hex(_avatar_hue(identity_id), saturation, lightness)


def parse_harness(raw: str | HarnessId | None) -> HarnessId | None:
    match raw:
        case None:
            return None
        case _:
            try:
                return HarnessId(raw)
            except ValueError:
                return None


def harness_badge(harness: str | HarnessId) -> HarnessBadge:
    """Lookup harness badge letters. ValueError on unknown — fail loud, never guess."""
    return HARNESS_BADGES[HarnessId(harness)]
