"""The groups a hold-and-split verdict names as drivers (spec: hold-and-split, a driver that is
a file or matches nothing)."""

from __future__ import annotations

from agent_build_kit.config import CeilingsConfig
from agent_build_kit.pipeline.verdict import GroupText, ReviewTier, TierVerdict, compute_verdict
from tests.verdict_support import green_facts

GROUPS = (
    GroupText(
        number=1,
        text="- [ ] 1.1 Test: in `tests/test_a.py` rounds of 3, Estimate: about 360 changed lines",
    ),
    GroupText(number=2, text="- [ ] 2.1 Edit `src/billing/refund.py`, about 280 lines"),
    GroupText(number=3, text="- [ ] 3.1 Change `src/billing/charge.py` and its test"),
    GroupText(number=4, text="- [ ] 4.1 Document it"),
)


def held(*drivers: str) -> TierVerdict:
    facts = green_facts(
        planned_estimate=ReviewTier.AUTO,
        classification=ReviewTier.FULL,
        changed_lines=5000,
        drivers=drivers,
        groups=GROUPS,
    )
    return compute_verdict(facts, ceilings=CeilingsConfig(), buffer=0.2)


def drivers_of(*named: str) -> tuple[int, ...]:
    result = held(*named)
    assert result.split is not None
    return result.split.drivers


def test_a_driver_naming_group_3_is_group_3() -> None:
    assert drivers_of("group 3") == (3,)


def test_a_driver_naming_a_file_group_3s_task_text_names_is_group_3() -> None:
    assert drivers_of("src/billing/charge.py") == (3,)


def test_a_driver_naming_a_file_no_group_names_is_dropped() -> None:
    assert drivers_of("group 2", "src/other/unknown.py") == (2,)


def test_a_verdict_whose_drivers_all_drop_carries_none() -> None:
    assert drivers_of("src/other/unknown.py") == ()


def test_a_driver_outside_the_units_groups_is_dropped() -> None:
    assert drivers_of("group 9", "group 4") == (4,)


def test_drivers_are_kept_in_group_order_once_each() -> None:
    assert drivers_of("src/billing/charge.py", "group 1", "group 3") == (1, 3)


def test_a_bare_number_is_the_group_and_matches_no_digits_in_task_text() -> None:
    assert drivers_of("3") == (3,)


def test_a_driver_with_a_title_after_the_group_number_is_that_group() -> None:
    assert drivers_of("group 3: the size step") == (3,)
    assert drivers_of("Task group 3 (verdict)") == (3,)


def test_a_file_matches_as_a_whole_path_and_not_inside_a_longer_name() -> None:
    groups = (GroupText(number=1, text="- [ ] 1.1 Edit `src/billing/surcharge.py`"),)
    facts = green_facts(
        planned_estimate=ReviewTier.AUTO,
        classification=ReviewTier.FULL,
        changed_lines=5000,
        drivers=("charge.py",),
        groups=groups,
    )

    result = compute_verdict(facts, ceilings=CeilingsConfig(), buffer=0.2)

    assert result.split is not None
    assert result.split.drivers == ()
