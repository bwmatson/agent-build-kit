"""With per-tier sizing on, the planner is told to keep a group it expects to get full review
apart from other work (spec: unit-sizing). The flag-off prompt is pinned byte for byte by
`test_planner_flag_off_prompt_unchanged.py`."""

from __future__ import annotations

import pytest

from tests.calibration_support import limits
from tests.prompt_text import flat
from tests.tier_ceiling_support import configure
from tests.tier_prompt_support import prompt_for


@pytest.fixture(autouse=True)
def per_tier_sizing() -> None:
    limits()
    configure(enabled=True)


def separation_paragraph(prompt: str) -> str:
    return next(part for part in prompt.split("\n\n") if "full review" in part and "only" in part)


def test_the_instructions_keep_a_full_review_group_in_a_unit_with_only_such_groups() -> None:
    paragraph = separation_paragraph(prompt_for([])).lower()

    assert "unit" in paragraph and "group" in paragraph


def test_the_instructions_say_why() -> None:
    paragraph = separation_paragraph(prompt_for([])).lower()

    assert "because" in paragraph or "so that" in paragraph or "otherwise" in paragraph


def test_the_instructions_do_not_say_the_tier_never_changes_grouping() -> None:
    assert "never changes how work is grouped" not in flat(prompt_for([]))
