"""The pipeline skill and the documents say what a replaced unit's successor is and what the
words `replaced by`, `replaced:` and `dependency X is now Y` mean (spec:
a-replaced-unit-points-to-its-successor)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit import skills
from tests.prompt_text import flat

DOCS = Path(__file__).resolve().parents[2] / "docs"


def test_the_pipeline_skill_names_the_field_and_the_words_the_pipeline_prints() -> None:
    text = flat(skills.source("abk-pipeline")).lower()

    assert "superseded_by" in text
    assert "replaced by" in text
    assert "is now" in text
    assert "replaced:" in text


@pytest.mark.parametrize("name", ["designs/unit-graph.md", "architecture.md"])
def test_a_document_names_the_field_beside_the_dependency_rules(name: str) -> None:
    blocks = re.split(r"\n\s*\n", (DOCS / name).read_text(encoding="utf-8"))

    beside = [flat(b) for b in blocks if "superseded_by" in b and "depend" in b.lower()]

    assert beside, f"{name} has no paragraph naming superseded_by with the dependency rules"
