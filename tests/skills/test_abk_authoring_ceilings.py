"""The `abk-authoring` skill says a group need not be split to fit a ceiling, that the planner
sizes by the review tier it expects, and that a group names what it touches; the installed mirror
that `abk install-skills` writes to `.claude/skills` holds the same text."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit import skills
from tests.prompt_text import flat

HEADING = "Say which files and paths a group touches"


@pytest.fixture
def raw_texts(tmp_path: Path) -> list[str]:
    """The source skill and the mirror the installer writes."""
    skills.install(tmp_path / ".claude" / "skills")
    mirror = tmp_path / ".claude" / "skills" / "abk-authoring" / "SKILL.md"
    return [skills.source("abk-authoring"), mirror.read_text(encoding="utf-8")]


@pytest.fixture
def texts(raw_texts: list[str]) -> list[str]:
    return [flat(text) for text in raw_texts]


def section(text: str) -> str:
    """The text under the heading, up to the next `## ` heading."""
    match = re.search(rf"^## {re.escape(HEADING)}\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    assert match, HEADING
    return flat(match.group(1))


def test_a_group_need_not_be_split_to_fit_a_single_ceiling(texts: list[str]) -> None:
    for text in texts:
        assert re.search(
            r"need not be split to (fit|dodge|stay under) a (single|size) ceiling", text
        )


def test_the_planner_sizes_a_unit_by_the_review_tier_it_expects(texts: list[str]) -> None:
    for text in texts:
        assert "planner sizes a unit by the review tier it expects" in text


def test_a_group_names_the_files_boundaries_or_behaviours_it_touches(texts: list[str]) -> None:
    for text in texts:
        lowered = text.lower()
        assert "files" in lowered
        assert "boundaries" in lowered
        assert "behaviours" in lowered
        assert "without naming functions" in lowered


def test_no_advice_to_split_to_stay_under_750_lines(texts: list[str]) -> None:
    for text in texts:
        assert not re.search(r"split.{0,80}\b750\b|\b750\b.{0,80}split", text, re.I)


def test_the_source_skill_and_the_mirror_hold_the_same_paragraph(raw_texts: list[str]) -> None:
    source, mirror = (section(text) for text in raw_texts)
    assert source == mirror
