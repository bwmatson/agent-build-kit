"""The pipeline skill and the documents describe the four build modes, the marker taxonomy and the
mode table of the prompts, and the changelog has a bullet for it (spec: group-build-modes)."""

from __future__ import annotations

import pytest

from agent_build_kit import skills
from tests.doc_text import ROOT, cli_entry, squashed, unreleased_bullets

MODES = ("tests_and_code", "tests_only", "no_code", "refactor")
DOCUMENTS = {
    "architecture": ROOT / "docs" / "architecture.md",
    "unit-graph": ROOT / "docs" / "designs" / "unit-graph.md",
}


def test_the_pipeline_skill_describes_the_four_modes_and_the_prompt_table() -> None:
    text = squashed(skills.source("abk-pipeline"))

    for mode in MODES:
        assert f"build mode {mode}" in text
    assert "kind selectors" in text
    assert "mode table" in text


@pytest.mark.parametrize("name", sorted(DOCUMENTS))
def test_the_document_describes_the_four_modes_and_the_prompt_table(name: str) -> None:
    text = squashed(DOCUMENTS[name].read_text(encoding="utf-8"))

    for mode in MODES:
        assert f"build mode {mode}" in text
    assert "kind selectors" in text
    assert "mode table" in text


def test_the_architecture_document_names_the_marker_taxonomy() -> None:
    text = squashed(DOCUMENTS["architecture"].read_text(encoding="utf-8"))

    assert "marker taxonomy" in text


def test_the_tags_entry_shows_the_mode_of_each_group() -> None:
    entry = cli_entry("### `abk tags [CHANGE] [--all]`")

    for mode in MODES:
        assert f"build mode {mode}" in entry


def test_the_tags_entry_describes_a_reorganization_group() -> None:
    entry = cli_entry("### `abk tags [CHANGE] [--all]`")

    assert "reorganization" in entry
    assert "No group is given build mode `refactor` yet" not in entry


def test_the_replan_entry_says_the_planner_gives_a_mode_per_group() -> None:
    entry = cli_entry("### `abk replan [CHANGE|UNIT ...]")

    assert "mode of each group" in entry
    assert "kept" in entry


def test_the_changelog_has_a_bullet_for_it() -> None:
    bullets = [b for b in unreleased_bullets() if "build mode" in b]

    assert len(bullets) == 1
    assert "Tests: required" in bullets[0]
    assert "no_code" in bullets[0]
    assert "abk-authoring" in bullets[0] and "abk-pipeline" in bullets[0]
