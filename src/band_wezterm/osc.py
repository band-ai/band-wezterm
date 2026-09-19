"""OSC 1337 SetUserVar emitter — allowlisted display fields only (W5)."""

from __future__ import annotations

import base64
import sys
from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from band_wezterm.wezterm_cli import PaneId, send_text


class OscKey(StrEnum):
    """Non-secret display fields the host may push into WezTerm user-vars."""

    AGENT_ID = "band.agent.id"
    AGENT_NAME = "band.agent.name"
    AGENT_INITIALS = "band.agent.initials"
    AGENT_COLOR = "band.agent.color"
    AGENT_KIND = "band.agent.kind"
    AGENT_STATUS = "band.agent.status"
    AGENT_RUNTIME = "band.agent.runtime"
    AGENT_HARNESS = "band.agent.harness"
    AGENT_ROOM_COLORS = "band.agent.room_colors"
    ROOM_SLUG = "band.room.slug"
    ROOM_NAME = "band.room.name"
    ROOM_COLOR = "band.room.color"


ALLOWED_KEYS: Final[frozenset[OscKey]] = frozenset(OscKey)

OSC_PREFIX: Final = "\033]1337;SetUserVar="
OSC_SUFFIX: Final = "\007"


class DisallowedOscKeyError(ValueError):
    """Raised when emit() is asked to send a key outside ALLOWED_KEYS."""


def encode_payload(value: str) -> str:
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _coerce_key(key: OscKey | str) -> OscKey:
    if isinstance(key, OscKey):
        return key
    try:
        return OscKey(key)
    except ValueError as error:
        raise DisallowedOscKeyError(f"OSC key not allowlisted: {key}") from error


def format_sequence(key: OscKey | str, value: str) -> str:
    osc_key = _coerce_key(key)
    return f"{OSC_PREFIX}{osc_key.value}={encode_payload(value)}{OSC_SUFFIX}"


def emit(pane_id: PaneId, key: OscKey | str, value: str) -> None:
    """Write an allowlisted user-var to a pane. Raises on a disallowed key."""
    emit_many(pane_id, {key: value})


def emit_many(pane_id: PaneId, fields: Mapping[OscKey | str, str]) -> None:
    """Write several allowlisted user-vars in one ``wezterm cli send-text``."""
    payload = _joined_sequences(fields)
    if payload:
        send_text(pane_id, payload)


def emit_to_stdout(key: OscKey | str, value: str) -> None:
    """Emit into the current pane's own stdout (Control/agent self-announce)."""
    emit_many_to_stdout({key: value})


def emit_many_to_stdout(fields: Mapping[OscKey | str, str]) -> None:
    payload = _joined_sequences(fields)
    if payload:
        sys.stdout.write(payload)
        sys.stdout.flush()


def _joined_sequences(fields: Mapping[OscKey | str, str]) -> str:
    return "".join(format_sequence(key, value) for key, value in fields.items())
