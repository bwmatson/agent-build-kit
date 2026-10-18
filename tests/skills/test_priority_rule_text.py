"""The authoring skill, the architecture document and the changelog describe the priority rule."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit import skills
from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]


def _section(text: str, heading: str) -> str:
    """The body under `heading` (a markdown heading line) up to the next heading of its level."""
    level = len(heading) - len(heading.lstrip("#"))
    start = text.index(heading + "\n") + len(heading)
    nxt = re.search(rf"^#{{1,{level}}} ", text[start:], re.MULTILINE)
    return text[start : start + nxt.start()] if nxt else text[start:]


def test_the_priority_section_says_a_group_is_at_least_as_urgent_as_its_dependents() -> None:
    section = flat(_section(skills.source("abk-authoring"), "## `Priority:` lines")).lower()

    assert "at least as urgent" in section
    assert "abk tags" in section
    assert "warn" in section
    assert "promoted" in section
    assert "independent:" in section


def test_the_separate_section_says_related_work_is_joined_first_then_the_more_urgent() -> None:
    section = flat(_section(skills.source("abk-authoring"), "## `Separate:` lines")).lower()

    assert "related" in section
    assert "more urgent" in section
    assert "most urgent" in section


def test_the_architecture_planning_section_says_the_join_order() -> None:
    text = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    section = flat(_section(text, "### 2. Planning into units")).lower()

    assert "logical grouping" in section
    assert "more urgent" in section
    assert "equal" in section


def test_the_changelog_names_the_reason_field_and_the_promotion_record() -> None:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = text.split("\n## ", 2)[1]

    assert "`needs_less_urgent`" in unreleased
    assert "`promoted_from`" in unreleased
