"""The skills and the changelog say a parked unit follows its group's `Split:` (spec:
a-parked-unit-follows-its-groups-split)."""

from __future__ import annotations

import re
from pathlib import Path

from agent_build_kit import skills
from tests.prompt_text import flat

ROOT = Path(__file__).resolve().parents[2]


def test_the_pipeline_skill_says_a_changed_split_reworks_a_parked_unit_and_a_held_one_defers() -> (
    None
):
    text = flat(skills.source("abk-pipeline")).lower()

    assert "split:" in text and "changed" in text
    assert "rework" in text
    assert "abk replan" in text
    assert "held" in text and "defer" in text


def test_the_authoring_skill_says_an_edit_of_a_started_units_split_takes_effect_when_parked() -> (
    None
):
    text = flat(skills.source("abk-authoring")).lower()

    assert "parked" in text and "reworked" in text
    assert "started unit" in text
    assert "held" in text and "defer" in text


def test_the_changelog_has_the_bullet_once_under_unreleased() -> None:
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = re.split(r"^## ", changelog, flags=re.MULTILINE)[1]
    bullets = [b for b in re.split(r"\n\s*\n", unreleased) if "Split:" in b and "parked" in b]

    assert unreleased.startswith("Unreleased")
    assert len(bullets) == 1
    assert "rework" in flat(bullets[0]).lower()
