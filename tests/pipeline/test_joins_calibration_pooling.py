"""A join of an integration-test unit is checked against the ceiling by the unit-test ratio."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.joins import JoinContext, JoinRefused, check_joins
from agent_build_kit.pipeline.unit_size import Calibration, Kind
from agent_build_kit.pipeline.units import Join
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.factories import ordinary_floor
from tests.factories import tiered_stored_unit as stored_unit

RATIOS = {Kind(repo="app", tier="unit-test"): Calibration(ratio=1.5, samples=20)}


def tagged(kind: str) -> TaskGroup:
    return TaskGroup(number=1, repo="app", tier=kind, title="A group", line=3, task_count=2)


def join_group(onto_kind: str, group_kind: str) -> None:
    onto = stored_unit("base/1", change="base", tier=onto_kind, estimated_lines=500)
    check_joins(
        [Join(onto="base/1", change="feature", groups=(1,), estimated_lines=100)],
        context=JoinContext(stored=(onto,), catalog={"base": (tagged(onto_kind),)}),
        plan=[],
        change="feature",
        groups=[tagged(group_kind)],
        built=set(),
        floor=ordinary_floor,
        calibrations=RATIOS,
    )


@pytest.mark.parametrize(
    ("onto_kind", "group_kind"),
    [
        ("integration-test", "unit-test"),
        ("integration-test", "integration-test"),
    ],
)
def test_the_ceiling_is_checked_with_the_unit_test_ratio(onto_kind: str, group_kind: str) -> None:
    # 500 + 100 is under 750 raw and over it at the ratio of 1.5.
    with pytest.raises(JoinRefused, match=r"times 1\.50 \(from 20 samples\)"):
        join_group(onto_kind, group_kind)
