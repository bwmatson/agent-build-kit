"""The skills and the documents say what a `Split:` line is, that a unit in a held e2e-test split
is not started, and how a test for two splits is written (spec: split-start-gate,
e2e-split-declaration)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit import skills
from tests.prompt_text import flat

DOCS = Path(__file__).resolve().parents[2] / "docs"


def test_the_authoring_skill_gives_the_line_the_one_split_rule_and_the_two_groups_instruction() -> (
    None
):
    text = flat(skills.source("abk-authoring")).lower()

    assert "split:" in text
    assert "one split" in text
    assert "two groups" in text
    assert "rest" in text


def test_the_pipeline_skill_names_the_wait_reason_and_the_backstop() -> None:
    text = flat(skills.source("abk-pipeline")).lower()

    assert "waiting for e2e-test split" in text
    assert "backstop" in text
    assert "parks" in text or "parked" in text


@pytest.mark.parametrize("name", ["architecture.md", "cli.md"])
def test_a_document_names_the_wait_reason_of_a_unit_in_a_held_split(name: str) -> None:
    blocks = re.split(r"\n\s*\n", (DOCS / name).read_text(encoding="utf-8"))

    naming = [flat(b) for b in blocks if "waiting for e2e-test split" in flat(b)]

    assert naming, f"{name} has no paragraph naming `waiting for e2e-test split`"
    assert any("`split`" in b or "not started" in b for b in naming)


def test_the_configuration_document_says_a_repos_splits_are_what_a_split_line_may_name() -> None:
    blocks = re.split(r"\n\s*\n", (DOCS / "configuration.md").read_text(encoding="utf-8"))

    naming = [flat(b) for b in blocks if "`Split:`" in b]

    assert naming, "configuration.md has no paragraph naming the `Split:` line"
    assert any("e2e_splits" in b for b in naming)


def test_the_unit_graph_document_has_the_legend_line_for_a_unit_waiting_on_a_held_split() -> None:
    text = flat((DOCS / "designs/unit-graph.md").read_text(encoding="utf-8"))

    assert "held e2e-test split" in text
