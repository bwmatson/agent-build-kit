"""The skills, the documents and the changelog say a parent that builds nothing holds no one,
and what the looping notice means."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import skills
from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]
DOCUMENTS = ["unit-graph.md", "architecture.md"]


def document(name: str) -> str:
    return flat((ROOT / "docs" / name).read_text(encoding="utf-8")).lower()


def unreleased() -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    section = text.split("## Unreleased", 1)[1].split("\n## ", 1)[0]
    return flat(section).lower()


def test_the_pipeline_skill_names_the_looping_notice_and_the_dropped_dependency() -> None:
    text = flat(skills.source("abk-pipeline")).lower()

    for term in ("looping:", "(looping)", "put back to planned", "dropped dependency"):
        assert term in text, term
    assert "abk requeue" in text
    assert "held repeatedly by" in text


def test_the_config_skill_lists_both_settings() -> None:
    text = flat(skills.source("abk-config")).lower()

    assert "bounce_limit" in text
    assert "bounce_span_seconds" in text


@pytest.mark.parametrize("name", DOCUMENTS)
def test_the_documents_name_the_states_that_build_nothing_beside_the_upstream_cause(
    name: str,
) -> None:
    text = document(name)

    for term in ("builds_nothing", "unplanned", "retired", "upstream_went_back", "looping"):
        assert term in text, term


def test_the_unit_graph_document_says_link_needs_drops_the_edge_and_how_a_bounce_is_counted() -> (
    None
):
    text = document("unit-graph.md")

    assert "link_needs" in text
    assert "dropped dependency" in text
    assert "bounce" in text
    assert "bounce_limit" in text


def test_the_architecture_document_says_the_notice_is_visibility_only() -> None:
    assert "visibility only" in document("architecture.md")


def test_the_changelog_has_a_bullet_for_it_under_unreleased() -> None:
    text = unreleased()

    assert "looping" in text
    assert "builds nothing" in text
