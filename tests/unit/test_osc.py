"""Unit tests for OSC allowlist + encoding."""

from __future__ import annotations

import base64

import pytest

from band_wezterm.osc import (
    ALLOWED_KEYS,
    DisallowedOscKeyError,
    OscKey,
    emit,
    encode_payload,
    format_focus_sequence,
    format_sequence,
)
from band_wezterm.wezterm_cli import PaneId


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[tuple[PaneId, str]]:
    """Capture what emit() would hand to `wezterm cli send-text`."""
    captured: list[tuple[PaneId, str]] = []
    monkeypatch.setattr(
        "band_wezterm.wezterm_cli.send_text",
        lambda pane_id, text: captured.append((pane_id, text)),
    )
    return captured


def test_encode_payload_is_standard_base64() -> None:
    assert encode_payload("hello") == base64.b64encode(b"hello").decode("ascii")


def test_format_sequence_for_allowed_key() -> None:
    sequence = format_sequence(OscKey.AGENT_NAME, "Ada")
    assert sequence.startswith("\033]1337;SetUserVar=band.agent.name=")
    assert sequence.endswith("\007")
    payload = sequence.split("=", 2)[-1].rstrip("\007")
    assert base64.b64decode(payload) == b"Ada"


def test_disallowed_key_raises() -> None:
    with pytest.raises(DisallowedOscKeyError):
        format_sequence("band.secret.token", "nope")


def test_every_allowed_key_emits_a_decodable_sequence(
    sent: list[tuple[PaneId, str]],
) -> None:
    for key in sorted(ALLOWED_KEYS, key=lambda item: item.value):
        emit(PaneId(3), key, f"value for {key.value}")

    assert [pane_id.root for pane_id, _ in sent] == [3] * len(ALLOWED_KEYS)
    ordered = sorted(ALLOWED_KEYS, key=lambda item: item.value)
    for key, (_, sequence) in zip(ordered, sent, strict=True):
        payload = sequence.removeprefix(
            f"\033]1337;SetUserVar={key.value}="
        ).removesuffix("\007")
        assert base64.b64decode(payload).decode("utf-8") == f"value for {key.value}"


def test_emit_rejects_disallowed_key_without_writing(
    sent: list[tuple[PaneId, str]],
) -> None:
    with pytest.raises(DisallowedOscKeyError):
        emit(PaneId(3), "band.agent.token", "leak")
    assert sent == []


def test_allowlist_contains_presence_split_and_room_colors() -> None:
    assert OscKey.AGENT_STATUS in ALLOWED_KEYS
    assert OscKey.AGENT_RUNTIME in ALLOWED_KEYS
    assert OscKey.AGENT_ROOM_COLORS in ALLOWED_KEYS
    assert OscKey.ROOM_COLOR in ALLOWED_KEYS
    assert OscKey.FOCUS in ALLOWED_KEYS
    assert "band.agent.presence" not in {key.value for key in ALLOWED_KEYS}


def test_format_focus_sequence_reuses_osc_framing() -> None:
    sequence = format_focus_sequence()
    assert sequence.startswith("\033]1337;SetUserVar=band.focus=")
    assert sequence.endswith("\007")
