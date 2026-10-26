"""The skills and the documents describe the emergency lane: a priority-0 unit starts as soon
as it is ready, in its own lane with its own cap, and no text still says that priority 0
bypasses no limit."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import skills
from tests.prompt_text import flat

DOCS = Path(__file__).resolve().parents[2] / "docs"
DOCUMENTS = ["configuration.md", "architecture.md", "cli.md", "designs/unit-graph.md"]


def document(name: str) -> str:
    return flat((DOCS / name).read_text(encoding="utf-8")).lower()


def test_the_authoring_skill_says_zero_is_rare_and_starts_in_the_lane_with_no_limit_edit() -> None:
    text = flat(skills.source("abk-authoring")).lower()

    assert "rare" in text
    assert "next tick" in text
    assert "emergency lane" in text
    assert "no limit edit" in text


def test_the_config_skill_lists_the_lane_cap() -> None:
    text = flat(skills.source("abk-config")).lower()

    assert "emergency_extra" in text
    assert "lane cap" in text
    assert "default 1" in text
    assert "0 is off" in text


def test_the_pipeline_skill_names_the_lane_and_says_ordinary_starts_wait() -> None:
    text = flat(skills.source("abk-pipeline")).lower()

    assert "emergency lane" in text
    assert "emergency room" in text
    assert "ordinary starts wait" in text


@pytest.mark.parametrize("name", ["abk-authoring", "abk-config", "abk-pipeline"])
def test_no_skill_says_priority_zero_bypasses_no_limit(name: str) -> None:
    assert "emergency lane" in flat(skills.source(name)).lower()
    assert "bypasses no limit" not in flat(skills.source(name)).lower()


@pytest.mark.parametrize("name", DOCUMENTS)
def test_each_document_names_the_lane_cap_and_none_says_zero_bypasses_no_limit(name: str) -> None:
    text = document(name)

    assert "emergency_extra" in text
    assert "bypasses no limit" not in text


def test_the_architecture_document_says_when_zero_starts_and_what_it_counts_for() -> None:
    text = document("architecture.md")

    assert "as soon as it is ready" in text
    assert "own cap" in text
    assert "occupancy" in text
    assert "never delays a unit that is finishing" in text
