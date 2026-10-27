"""The documents and the skill say what happens to a unit over its ceiling that cannot be split,
the setting that chooses it and how to keep the old behaviour (spec: unsplittable-size)."""

from __future__ import annotations

import re

from tests.doc_text import ROOT, squashed

SKILL = ROOT / "src" / "agent_build_kit" / "skills" / "abk-pipeline" / "SKILL.md"


def section_after(text: str, marker: str, length: int) -> str:
    return text[text.index(marker) :][:length]


def assert_says_it(text: str, name: str) -> None:
    assert re.search(r"cannot be split|can't be split|not split|unsplit", text, re.I), name
    assert re.search(r"waive[sd]?", text, re.I), f"{name} lacks the waived size rule"
    assert re.search(r"pull request", text, re.I), f"{name} lacks the pull request"
    assert "review.unsplittable" in text, f"{name} lacks the setting"
    assert re.search(r"unsplittable.{0,80}\bhold\b", text, re.I), (
        f"{name} lacks how to keep the old behaviour"
    )


def test_the_unit_graph_design_says_it() -> None:
    text = squashed((ROOT / "docs" / "designs" / "unit-graph.md").read_text(encoding="utf-8"))
    assert_says_it(section_after(text, "too_big_for_tier", 2500), "docs/designs/unit-graph.md")


def test_the_architecture_size_hold_paragraph_says_it() -> None:
    text = squashed((ROOT / "docs" / "architecture.md").read_text(encoding="utf-8"))
    assert_says_it(section_after(text, "The size hold and the split", 2500), "docs/architecture.md")


def test_the_configuration_review_block_says_it() -> None:
    text = squashed((ROOT / "docs" / "configuration.md").read_text(encoding="utf-8"))
    block = section_after(text, "### review", 6000)
    assert "unsplittable" in block, "docs/configuration.md lacks the setting"
    assert "open_pr" in block, "docs/configuration.md lacks the default"
    assert re.search(r"unsplittable.{0,200}\bhold\b", block), "and how to keep the old behaviour"


def test_the_pipeline_skill_size_hold_paragraph_says_it() -> None:
    text = squashed(SKILL.read_text(encoding="utf-8"))
    paragraph = section_after(text, "A size hold", 1800)
    assert_says_it(paragraph, "abk-pipeline skill")
    assert "requeue" in paragraph
