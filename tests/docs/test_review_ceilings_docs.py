"""The documents and the skills describe review ceilings, stale plans and sizing by tier."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / "src" / "agent_build_kit" / "skills"
DOCS = ROOT / "docs"
SETTING_DOCUMENTS = (DOCS / "configuration.md", SKILLS / "abk-config" / "SKILL.md")
SETTING_IDS = ["configuration.md", "abk-config-skill"]
STALE_DOCUMENTS = (DOCS / "cli.md", SKILLS / "abk-pipeline" / "SKILL.md")
STALE_IDS = ["cli.md", "abk-pipeline-skill"]


def squashed(path: Path) -> str:
    """The file's text on one line with the code ticks dropped, so a wrapped sentence matches."""
    return " ".join(path.read_text(encoding="utf-8").replace("`", "").split())


@pytest.mark.parametrize("path", SETTING_DOCUMENTS, ids=SETTING_IDS)
def test_the_ceilings_are_named_with_their_three_defaults(path: Path) -> None:
    text = squashed(path)
    assert "review.ceilings" in text or re.search(r"\bceilings:", text)
    for figure in ("5000", "2000", "750"):
        assert re.search(rf"ceilings.{{0,900}}\b{figure}\b", text, re.I), figure
    for tier in ("auto", "light", "full"):
        assert re.search(rf"ceilings.{{0,900}}\b{tier}\b", text, re.I), tier


@pytest.mark.parametrize("path", SETTING_DOCUMENTS, ids=SETTING_IDS)
def test_a_repo_can_override_the_ceilings(path: Path) -> None:
    text = squashed(path)
    assert re.search(r"repos?\b.{0,300}ceilings|ceilings.{0,500}\b(repo|repos)\b", text, re.I)
    assert re.search(r"ceilings.{0,300}override|override.{0,300}ceilings", text, re.I)


def test_the_authoring_skill_says_what_a_group_states_about_its_files() -> None:
    text = squashed(SKILLS / "abk-authoring" / "SKILL.md")
    assert re.search(r"\b(files?|paths?)\b.{0,200}\b(touch|touches|touched)\b", text, re.I)
    assert re.search(r"expected (review )?tier|tier.{0,80}estimat", text, re.I)


def test_the_authoring_skill_says_a_group_need_not_be_split_for_a_ceiling() -> None:
    text = squashed(SKILLS / "abk-authoring" / "SKILL.md")
    assert re.search(
        r"(need not|no longer|does not have to|do not have to|not).{0,60}split.{0,200}ceiling",
        text,
        re.I,
    )


@pytest.mark.parametrize("path", STALE_DOCUMENTS, ids=STALE_IDS)
def test_the_stale_plan_listing_is_named(path: Path) -> None:
    text = squashed(path)
    assert re.search(r"replan.{0,500}\bstale\b|\bstale\b.{0,500}replan", text, re.I)
    assert re.search(r"stale plans?", text, re.I)
    assert re.search(r"sizing|review\.enabled|ceilings", text, re.I)


def test_the_architecture_says_a_unit_is_sized_by_its_expected_tier() -> None:
    text = squashed(DOCS / "architecture.md")
    assert re.search(r"sized by its expected (review )?tier", text, re.I)
    assert re.search(r"expected (review )?tier.{0,400}ceiling", text, re.I)
