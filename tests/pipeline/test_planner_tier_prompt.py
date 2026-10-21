"""With per-tier sizing on, the planner is told each tier's ceiling and each overriding repo's,
and the calibration section's largest raw estimate is worked out from those ceilings
(spec: review-tier-ceilings)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.unit_size import largest_raw
from tests.calibration_support import limits
from tests.tier_ceiling_support import configure
from tests.tier_prompt_support import landed_at_one_and_a_half, prompt_for, ratio_of

OPENS = "Estimates are your raw figures"
CLOSES = "Changes ready to plan"


def calibration_section(prompt: str) -> str:
    return prompt[prompt.index(OPENS) : prompt.index(CLOSES)]


def ceilings_paragraph(prompt: str) -> str:
    """The paragraph of the instructions that states the tier ceilings."""
    return next(part for part in prompt.split("\n\n") if "5000" in part and "2000" in part)


@pytest.fixture(autouse=True)
def per_tier_sizing() -> None:
    limits()
    configure(enabled=True)


def test_the_instructions_give_the_three_ceilings() -> None:
    paragraph = ceilings_paragraph(prompt_for([]))

    for tier, ceiling in (("auto", "5000"), ("light", "2000"), ("full", "750")):
        assert tier in paragraph and ceiling in paragraph


def test_the_instructions_say_a_unit_is_held_to_its_expected_tiers_ceiling() -> None:
    paragraph = ceilings_paragraph(prompt_for([])).lower()

    assert "expect" in paragraph and "tier" in paragraph and "ceiling" in paragraph
    assert "plan" in paragraph


def test_the_instructions_give_a_repos_override() -> None:
    configure(enabled=True, repo_ceilings={"auto": 3000})

    paragraph = ceilings_paragraph(prompt_for([]))

    assert any("app" in line and "3000" in line for line in paragraph.splitlines())


def test_a_repo_without_an_override_is_not_listed() -> None:
    assert "3000" not in prompt_for([])


def test_the_largest_raw_estimate_is_each_tiers_ceiling_over_the_ratio() -> None:
    units = landed_at_one_and_a_half()
    ratio = ratio_of(units).ratio

    section = calibration_section(prompt_for(units))

    assert ratio > 1.0
    for ceiling in (5000, 2000, 750):
        assert str(largest_raw(ceiling, ratio)) in section


def test_a_repos_override_is_what_the_largest_raw_estimate_is_computed_from() -> None:
    configure(enabled=True, repo_ceilings={"auto": 3000})
    units = landed_at_one_and_a_half()
    ratio = ratio_of(units).ratio

    section = calibration_section(prompt_for(units))

    assert str(largest_raw(3000, ratio)) in section
    assert str(largest_raw(5000, ratio)) not in section
