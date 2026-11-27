"""The documents, the skills and the changelog describe what a unit stores and shows."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[2]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
DOCUMENTS = {
    "docs/designs/unit-graph.md": ROOT / "docs" / "designs/unit-graph.md",
    "abk-pipeline": SKILLS / "abk-pipeline" / "SKILL.md",
    "abk-authoring": SKILLS / "abk-authoring" / "SKILL.md",
}


def words(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text()).lower()


@pytest.mark.parametrize("name", DOCUMENTS)
def test_the_document_gives_the_rule_of_direct_dependencies(name: str) -> None:
    text = words(DOCUMENTS[name])

    assert "direct_dependencies" in text
    assert "does not reach" in text


@pytest.mark.parametrize("name", DOCUMENTS)
def test_the_document_says_the_acceptance_wait_is_computed_at_run_time(name: str) -> None:
    text = words(DOCUMENTS[name])

    assert "run time" in text
    assert "every earlier unit" in text


@pytest.mark.parametrize("name", ["docs/designs/unit-graph.md", "abk-authoring"])
def test_the_document_says_a_needs_the_chain_implies_draws_no_edge(name: str) -> None:
    text = words(DOCUMENTS[name])

    assert "implies" in text
    assert "no edge" in text
