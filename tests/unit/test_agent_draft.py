"""Agent draft naming — platform registration contract."""

from __future__ import annotations

from band_wezterm.agent_draft import (
    AGENT_NAME_MAX,
    AGENT_NAME_MIN,
    NAME_FORBIDDEN_MESSAGE,
    AgentDraft,
    agent_name_error,
    draft_name,
    suggested_agent_name,
    unique_suffix,
)
from band_wezterm.roles import Role


def test_unique_suffix_is_short_base36() -> None:
    generated = unique_suffix()
    assert len(generated) == 6
    assert generated.isalnum()
    assert generated == generated.lower()


def test_suggested_name_strips_platform_forbidden_characters() -> None:
    suggested = suggested_agent_name("Developer @ VS/Code", "a1b2c3")
    assert suggested == "Developer VS Code a1b2c3"
    assert agent_name_error(suggested) is None


def test_suggested_name_clamps_long_labels() -> None:
    suggested = suggested_agent_name("a" * (AGENT_NAME_MAX * 2), "a1b2c3")
    assert len(suggested) <= AGENT_NAME_MAX
    assert suggested.endswith(" a1b2c3")


def test_draft_name_sanitizes_role_labels() -> None:
    draft = AgentDraft(
        role=Role(
            id="ux-ui-product-designer",
            label="UX/UI Product Designer",
            content="# UX/UI Product Designer\n",
        ),
        name_suffix="a1b2c3",
    )
    assert draft_name(draft) == "UX UI Product Designer a1b2c3"
    assert agent_name_error(draft_name(draft)) is None


def test_agent_name_error_matches_platform_rules() -> None:
    assert agent_name_error("") == "Name is required."
    assert agent_name_error("ab") == f"Name must be at least {AGENT_NAME_MIN} characters."
    assert (
        agent_name_error("a" * (AGENT_NAME_MAX + 1))
        == f"Name must be at most {AGENT_NAME_MAX} characters."
    )
    assert agent_name_error("Developer @ Band") == NAME_FORBIDDEN_MESSAGE
    assert agent_name_error("Developer/Reviewer") == NAME_FORBIDDEN_MESSAGE
    assert agent_name_error("Developer") is None
