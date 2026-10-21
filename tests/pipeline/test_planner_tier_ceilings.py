"""With per-tier sizing on, a unit is held to the ceiling of its expected review tier, after
calibration (spec: unit-sizing)."""

from __future__ import annotations

from collections.abc import Mapping

import pytest

from agent_build_kit.pipeline.planner import Plan, PlannerError, parse_plan
from agent_build_kit.pipeline.unit_size import Calibration, Kind
from tests.tier_ceiling_support import GROUPS, configure, graph

APP = Kind(repo="app", tier="unit-test")


@pytest.fixture(autouse=True)
def per_tier_sizing() -> None:
    configure(enabled=True)


def plan(tier: str, lines: int, *, found: Mapping[Kind, Calibration] | None = None) -> Plan:
    unit = {"id": "c/1", "groups": [1, 2, 3], "estimated_lines": lines, "review_tier": tier}
    return parse_plan(graph(unit), groups=GROUPS, calibrations=found)


def refusal(tier: str, lines: int, *, found: Mapping[Kind, Calibration] | None = None) -> str:
    with pytest.raises(PlannerError) as refused:
        plan(tier, lines, found=found)
    return str(refused.value)


def test_an_auto_unit_under_the_auto_ceiling_is_accepted() -> None:
    assert plan("auto", 2000).units[0].review_tier == "auto"


def test_an_auto_unit_over_the_auto_ceiling_is_refused_naming_tier_and_ceiling() -> None:
    message = refusal("auto", 5200)

    assert "auto" in message
    assert "5000" in message


def test_a_light_unit_over_the_light_ceiling_is_refused_naming_the_tier() -> None:
    message = refusal("light", 2100)

    assert "light" in message
    assert "2000" in message


def test_a_ratio_applies_before_the_tiers_ceiling_and_is_named() -> None:
    message = refusal("auto", 3500, found={APP: Calibration(ratio=1.5, samples=20)})

    for named in ("5250", "5000", "1.5", "20"):
        assert named in message


def test_a_reply_that_names_no_tier_is_held_to_the_full_ceiling_though_its_floor_is_auto() -> None:
    unit = {"id": "c/1", "groups": [1, 2, 3], "estimated_lines": 800}

    with pytest.raises(PlannerError, match="750"):
        parse_plan(graph(unit), groups=GROUPS)


def test_a_reply_that_names_no_tier_is_still_recorded_at_its_floor() -> None:
    unit = {"id": "c/1", "groups": [1, 2, 3], "estimated_lines": 700}

    assert parse_plan(graph(unit), groups=GROUPS).units[0].review_tier == "auto"


def test_a_unit_whose_floor_is_full_and_names_no_tier_is_held_to_the_full_ceiling() -> None:
    # A contract group's floor is full, so a reply that omits the tier is given it.
    flagged = [group.model_copy(update={"flag": "contract"}) for group in GROUPS]
    unit = {"id": "c/1", "groups": [1, 2, 3], "estimated_lines": 800}

    with pytest.raises(PlannerError, match="750"):
        parse_plan(graph(unit), groups=flagged)


def test_a_repos_override_is_the_ceiling_for_that_repos_units() -> None:
    configure(enabled=True, repo_ceilings={"auto": 3000})

    assert plan("auto", 2900).units[0].estimated_lines == 2900
    message = refusal("auto", 3500)
    assert "3000" in message
    assert "5000" not in message
