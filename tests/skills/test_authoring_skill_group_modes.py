"""The `abk-authoring` skill says that only a group that touches code writes tests first, describes
the `Tests:` line and teaches how the planner judges a change to documents or configuration, and the
authoring prompt of `abk init` keeps the exception (spec: group-build-modes)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit import skills
from agent_build_kit.init import propose
from tests.prompt_text import flat

HEADING = "How the planner judges a change to documents or configuration"


@pytest.fixture
def raw_texts(tmp_path: Path) -> list[str]:
    """The source skill and the mirror the installer writes."""
    skills.install(tmp_path / ".claude" / "skills")
    mirror = tmp_path / ".claude" / "skills" / "abk-authoring" / "SKILL.md"
    return [skills.source("abk-authoring"), mirror.read_text(encoding="utf-8")]


def section(text: str) -> str:
    """The text under the heading, up to the next heading of the same or a higher level."""
    match = re.search(rf"^(#+) {re.escape(HEADING)}\n(.*?)(?=^#{{1,2}} |\Z)", text, re.M | re.S)
    assert match, HEADING
    return flat(match.group(2))


def test_the_skill_says_only_a_group_that_touches_code_writes_tests_first(
    raw_texts: list[str],
) -> None:
    for text in raw_texts:
        assert "only a group that touches code writes its tests first" in flat(text)


def test_the_skill_describes_the_tests_line(raw_texts: list[str]) -> None:
    for text in raw_texts:
        body = flat(text)
        assert "Tests: required — <reason>" in body
        assert "no line lowers a floor" in body


def test_the_section_judges_how_durable_and_critical_a_change_is(raw_texts: list[str]) -> None:
    for text in raw_texts:
        body = section(text)
        assert "durable" in body and "critical" in body
        assert "no_code" in body and "tests_and_code" in body


def test_the_section_shows_a_bad_and_a_good_example(raw_texts: list[str]) -> None:
    for text in raw_texts:
        body = section(text)
        assert re.search(r"\bbad\b", body, re.I)
        assert re.search(r"\bgood\b", body, re.I)


def test_the_skill_describes_how_to_write_a_reorganization_group(raw_texts: list[str]) -> None:
    for text in raw_texts:
        body = flat(text)
        assert "reorganization" in body
        assert "`refactor`" in body
        assert "no group is given build mode `refactor` yet" not in body


def test_the_authoring_prompt_keeps_the_exception() -> None:
    prompt = flat(propose.PROMPT)

    assert "Test tasks come before implementation tasks in every group." not in prompt
    assert "only a group that touches code" in prompt
