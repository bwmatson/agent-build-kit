"""The `abk-pipeline` skill, in its source and in the mirror the installer writes, has a section
on a unit that failed at the red check (spec: installed-skills-are-kept-current)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit import skills
from agent_build_kit.pipeline.unit_store import FeedbackSource
from tests.prompt_text import flat

HEADING = "A unit failed at the red check"


@pytest.fixture
def raw_texts(tmp_path: Path) -> list[str]:
    """The source skill and the mirror the installer writes."""
    skills.install(tmp_path / ".claude" / "skills")
    mirror = tmp_path / ".claude" / "skills" / "abk-pipeline" / "SKILL.md"
    return [skills.source("abk-pipeline"), mirror.read_text(encoding="utf-8")]


def section(text: str) -> str:
    """The squeezed, lowercased text under the heading, up to the next heading of the same or a
    higher level."""
    match = re.search(rf"^(#+) {re.escape(HEADING)}\n(.*?)(?=^#{{1,3}} |\Z)", text, re.M | re.S)
    assert match, HEADING
    return flat(match.group(2)).lower()


@pytest.mark.parametrize(
    "terms",
    [
        pytest.param(("passed at the tests commit",), id="tests-passed"),
        pytest.param(("nothing failed",), id="nothing-failed"),
        pytest.param(("no tests ran",), id="no-tests-ran"),
        pytest.param(("replay", "earlier"), id="earlier-rejection-replayed"),
    ],
)
def test_the_section_names_each_reason_the_check_gives(
    raw_texts: list[str], terms: tuple[str, ...]
) -> None:
    for text in raw_texts:
        body = section(text)
        for term in terms:
            assert term in body, term


def test_the_section_names_the_feedback_sources_as_stored(raw_texts: list[str]) -> None:
    for text in raw_texts:
        body = section(text)
        assert f"`{FeedbackSource.RED_CHECK.value}`" in body
        assert f"`{FeedbackSource.SELECTOR_CHECK.value}`" in body


def test_the_section_says_where_the_reasons_are_recorded(raw_texts: list[str]) -> None:
    for text in raw_texts:
        body = section(text)
        assert "feedback" in body
        assert "cache" in body


def test_the_section_says_how_to_tell_a_rejected_test_from_a_check_that_could_not_run(
    raw_texts: list[str],
) -> None:
    for text in raw_texts:
        body = section(text)
        assert "rejected" in body
        assert "could not run" in body


def test_the_section_says_a_plain_requeue_replays_an_earlier_rejection(
    raw_texts: list[str],
) -> None:
    for text in raw_texts:
        body = section(text)
        assert "abk requeue" in body
        assert "plain requeue" in body
