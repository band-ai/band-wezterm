"""Chat timeline event helpers — filter, preview, visibility."""

from __future__ import annotations

from band_wezterm.platform_models import MessageRecord
from band_wezterm.tui.chat_events import (
    DEFAULT_ALLOWED_TYPES,
    EVENT_PREVIEW_MAX_LENGTH,
    FILTERED_EMPTY_CHAT,
    VERBOSE_TYPES,
    EventFilterCategory,
    apply_verbose,
    badge_label,
    category_selected,
    count_by_category,
    error_display_content,
    event_preview,
    event_tag_class,
    hidden_summary,
    is_always_expanded,
    message_is_visible,
    normalize_allowed_types,
    select_all_categories,
    timeline_content,
    timeline_preview,
    toggle_category,
    verbose_active,
    visible_messages,
)


def test_event_preview_truncates_by_code_point() -> None:
    text = "a" * (EVENT_PREVIEW_MAX_LENGTH + 5)
    preview = event_preview(text)
    assert preview.endswith("…")
    assert len(list(preview[:-1])) == EVENT_PREVIEW_MAX_LENGTH


def test_event_preview_empty() -> None:
    assert event_preview("   \n  ") == "(no additional details)"


def test_event_preview_first_line_only() -> None:
    assert event_preview("one\ntwo") == "one"


def test_tool_result_timeline_preview_summarizes_success() -> None:
    message = MessageRecord(
        id="result-1",
        author_name="Developer",
        message_type="tool_result",
        content=(
            '{"name":"band_send_message","output":[{"type":"text",'
            '"text":"{\\"status\\":\\"success\\",\\"message\\":'
            '\\"Message sent\\"}"}]}'
        ),
    )

    assert timeline_preview(message) == "band_send_message · Message sent"


def test_event_tag_class_is_semantic_for_known_and_unknown_types() -> None:
    assert event_tag_class("tool_result") == "event-tag-tool-result"
    assert event_tag_class("future_event") == "event-tag-system"


def test_timeline_content_removes_redundant_platform_category_prefix() -> None:
    assert timeline_content("task", "[Task] Token usage: input=6") == "Token usage: input=6"
    assert timeline_content("participant", "[Participant] Ada joined") == "Ada joined"
    assert timeline_content("text", "[Task] User-authored text") == "[Task] User-authored text"


def test_default_visibility_hides_tools() -> None:
    tool = MessageRecord(
        id="t1", content="ToolSearch", author_name="a", message_type="tool_call"
    )
    text = MessageRecord(id="m1", content="hi", author_name="u", message_type="text")
    visible = visible_messages([tool, text], DEFAULT_ALLOWED_TYPES)
    assert [item.id for item in visible] == ["m1"]


def test_unknown_types_always_visible() -> None:
    unknown = MessageRecord(
        id="u1", content="x", author_name="a", message_type="guidelines"
    )
    assert message_is_visible(unknown, ())


def test_system_category_covers_participant() -> None:
    allowed = normalize_allowed_types(["system", "participant"])
    assert category_selected(EventFilterCategory.SYSTEM, allowed)
    toggled_off = toggle_category(EventFilterCategory.SYSTEM, allowed)
    assert "system" not in toggled_off
    assert "participant" not in toggled_off


def test_hidden_summary() -> None:
    messages = [
        MessageRecord(id="1", content="a", author_name="a", message_type="tool_call"),
        MessageRecord(id="2", content="b", author_name="a", message_type="tool_result"),
        MessageRecord(id="3", content="c", author_name="a", message_type="text"),
    ]
    summary = hidden_summary(messages, DEFAULT_ALLOWED_TYPES)
    assert summary == "Hidden: 1 tool calls, 1 tool results"


def test_verbose_round_trip() -> None:
    base = DEFAULT_ALLOWED_TYPES
    on = apply_verbose(base, enabled=True, previous=None)
    assert set(on) >= VERBOSE_TYPES
    assert verbose_active(on)
    off = apply_verbose(on, enabled=False, previous=base)
    assert set(off) == set(base)


def test_select_all_retains_unknown() -> None:
    allowed = ("text", "future_type")
    selected = select_all_categories(allowed)
    assert "future_type" in selected
    assert "tool_call" in selected


def test_error_provider_prefix() -> None:
    assert (
        error_display_content("boom", {"failure": {"provider": "openai"}})
        == "[openai] boom"
    )


def test_thought_is_always_expanded() -> None:
    assert is_always_expanded("thought")
    assert not is_always_expanded("tool_call")


def test_badge_unknown_falls_back_to_raw_type() -> None:
    assert badge_label("custom_event") == "custom_event"


def test_filtered_empty_copy_constant() -> None:
    assert "event type filter" in FILTERED_EMPTY_CHAT


def test_count_by_category_groups_system() -> None:
    messages = [
        MessageRecord(id="1", content="", author_name="a", message_type="system"),
        MessageRecord(id="2", content="", author_name="a", message_type="participant"),
    ]
    counts = count_by_category(messages)
    assert counts[EventFilterCategory.SYSTEM] == 2
