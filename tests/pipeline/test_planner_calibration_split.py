"""A rejection or a refused join for size says what the planner may write instead.

The plan check and the join check are called with the ratios a round computes, and the
messages are read as the planner is shown them.
"""

from __future__ import annotations

import json
import re

import pytest

from agent_build_kit.pipeline.joins import JoinContext, JoinRefused, check_joins
from agent_build_kit.pipeline.planner import GroupTooLarge, PlannerError, parse_plan
from agent_build_kit.pipeline.unit_size import Calibration, Kind
from agent_build_kit.pipeline.units import Join
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.calibration_support import limits
from tests.factories import stored_unit

APP = Kind(repo="app", tier="tier1")
RATIO_1_5 = {APP: Calibration(ratio=1.5, samples=20)}
GROUPS = [
    TaskGroup(number=n, repo="app", tier="tier1", title=title, line=3 + 6 * n, task_count=2)
    for n, title in enumerate("ABC", start=1)
]


def graph(*units: dict) -> str:
    body = [
        {"change": "c", "title": "A unit", "repo": "app", "tier": "tier1", **unit} for unit in units
    ]
    return json.dumps({"units": body})


def rejection(found: dict | None, estimate: int = 600) -> str:
    output = graph({"id": "c/1", "groups": [1, 2, 3], "estimated_lines": estimate})
    with pytest.raises(PlannerError, match="ceiling") as rejected:
        parse_plan(output, groups=GROUPS, calibrations=found)
    return str(rejected.value)


def test_a_combined_unit_over_the_ceiling_after_calibration_is_told_what_to_split_to() -> None:
    limits(max_unit_lines=750)

    message = rejection(RATIO_1_5)

    for named in ("900", "1.5", "20", "500"):
        assert named in message
    assert re.search(r"\b3 (task )?groups\b", message)
    assert "split" in message


def test_a_single_group_over_the_ceiling_is_reported_as_it_was() -> None:
    limits(max_unit_lines=750)
    output = graph(
        {"id": "c/1", "groups": [1], "estimated_lines": 600},
        {"id": "c/2", "groups": [2, 3], "estimated_lines": 100, "depends_on": ["c/1"]},
    )

    with pytest.raises(GroupTooLarge) as rejected:
        parse_plan(output, groups=GROUPS, calibrations=RATIO_1_5)

    assert "group 1" in str(rejected.value)
    assert "largest raw" not in str(rejected.value)
    # the combined unit's message is the one that carries the figure, so this one only differs by it
    assert "500" in rejection(RATIO_1_5)


def test_a_unit_over_the_ceiling_with_no_calibration_is_rejected_as_it_was() -> None:
    limits(max_unit_lines=750)
    assert "500" in rejection(RATIO_1_5)

    plain = rejection(None, estimate=900)

    assert "largest raw" not in plain
    assert not re.search(r"\b3 (task )?groups\b", plain)
    limits(max_unit_lines=750, calibrate_estimates=False)
    assert rejection(RATIO_1_5, estimate=900) == plain


def refusal(found: dict | None, *, added: int = 250) -> str:
    base = stored_unit("base/1", change="base", groups=(1,), estimated_lines=300)
    group = TaskGroup(number=1, repo="app", tier="tier1", title="A", line=3, task_count=2)
    other = TaskGroup(number=1, repo="app", tier="tier1", title="B", line=3, task_count=2)
    with pytest.raises(JoinRefused, match="ceiling") as refused:
        check_joins(
            [Join(onto="base/1", change="feature", groups=(1,), estimated_lines=added)],
            context=JoinContext(stored=(base,), catalog={"base": (other,)}),
            plan=[],
            change="feature",
            groups=[group],
            built=set(),
            ceiling=750,
            calibrations=found,
        )
    return str(refused.value)


def test_a_refused_join_names_the_largest_raw_estimate_of_the_receiving_kind() -> None:
    limits(max_unit_lines=750)

    message = refusal(RATIO_1_5)

    assert "750" in message and "1.50" in message
    assert "500" in message


def test_a_refused_join_with_calibration_off_is_as_it_was() -> None:
    limits(max_unit_lines=750)
    assert "500" in refusal(RATIO_1_5)

    limits(max_unit_lines=750, calibrate_estimates=False)

    assert refusal(RATIO_1_5, added=500) == refusal(None, added=500)
    assert "largest raw" not in refusal(None, added=500)
