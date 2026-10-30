"""The assessment of retiring a unit, decided from the units alone: whether it may be, what
becomes of each group it carries, who stops waiting, and whether a reason is required
(spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.retirement import Dependent, GroupFate, assess
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    Member,
    UnitState,
)
from tests.factories import stored_unit

RETIRED = UnitState.RETIRED
UNPLANNED = UnitState.UNPLANNED


def unit(uid: str, **overrides) -> StoredUnit:
    """A unit of change `app`, with the groups the test gives it."""
    return stored_unit(uid, change="app", **overrides)


def target(**overrides) -> StoredUnit:
    return unit("app/3", **{"groups": (16,), "branch": "spec/app/3", **overrides})


@pytest.mark.parametrize("state", [MERGED, CLOSED, SATISFIED, RETIRED])
def test_a_finished_unit_is_refused_as_finished(state: UnitState) -> None:
    found = assess("app/3", [target(state=state)])

    assert "finished" in found.refusal


def test_a_running_unit_is_not_refused_here_the_command_asks_who_holds_it() -> None:
    found = assess("app/3", [target(state=RUNNING)])

    assert found.refusal == ""


@pytest.mark.parametrize("state", [PLANNED, UNPLANNED, FAILED, HELD, IN_REVIEW])
def test_an_unfinished_unit_that_is_not_running_is_accepted(state: UnitState) -> None:
    found = assess("app/3", [target(state=state)])

    assert found.refusal == ""


def test_a_started_same_repo_dependent_stacked_on_the_unit_refuses_it_by_name() -> None:
    units = [
        target(),
        unit("app/5", groups=(17,), depends_on=("app/3",), branch="spec/app/5"),
    ]

    found = assess("app/3", units)

    assert "app/5" in found.refusal


@pytest.mark.parametrize(
    "dependent",
    [
        {"repo": "app"},
        {"repo": "platform", "branch": "spec/app/5"},
    ],
    ids=["dependent not started", "dependent in another repo"],
)
def test_a_dependent_that_is_not_stacked_on_the_unit_does_not_refuse_it(
    dependent: dict[str, str],
) -> None:
    units = [target(), unit("app/5", groups=(17,), depends_on=("app/3",), **dependent)]

    assert assess("app/3", units).refusal == ""


def test_each_group_is_carried_by_a_merged_unit_or_a_unit_still_owning_it() -> None:
    units = [
        target(groups=(16, 17)),
        unit("app/4", groups=(16,), state=MERGED),
        unit("app/5", groups=(17,), state=IN_REVIEW, pr=5),
    ]

    found = assess("app/3", units)

    assert found.groups == (
        GroupFate(change="app", group=16, carried_by="app/4", merged=True),
        GroupFate(change="app", group=17, carried_by="app/5", merged=False),
    )
    assert not found.reason_required


def test_a_satisfied_unit_has_built_the_group_it_carries() -> None:
    units = [target(), unit("app/4", groups=(16,), state=SATISFIED)]

    assert assess("app/3", units).groups == (
        GroupFate(change="app", group=16, carried_by="app/4", merged=True),
    )


def test_an_unplanned_unit_with_work_still_owns_the_group_it_carries() -> None:
    units = [target(), unit("app/4", groups=(16,), state=UNPLANNED, branch="spec/app/4")]

    found = assess("app/3", units)

    assert found.groups[0].carried_by == "app/4"
    assert not found.reason_required


@pytest.mark.parametrize(
    "other",
    [
        None,
        unit("app/4", groups=(16,), state=CLOSED),
        unit("app/4", groups=(16,), state=RETIRED, branch="spec/app/4"),
        unit("app/4", groups=(16,), state=UNPLANNED),
        stored_unit("beta/4", change="beta", groups=(16,)),
    ],
    ids=["no unit", "closed", "retired", "unplanned without work", "same number, other change"],
)
def test_a_group_no_unit_builds_is_unowned_and_needs_a_reason(other: StoredUnit | None) -> None:
    units = [target(), *([other] if other else [])]

    found = assess("app/3", units)

    assert found.groups == (GroupFate(change="app", group=16),)
    assert found.reason_required


def test_one_unowned_group_among_carried_ones_requires_a_reason() -> None:
    units = [target(groups=(16, 17)), unit("app/4", groups=(16,), state=MERGED)]

    found = assess("app/3", units)

    assert [fate.carried_by for fate in found.groups] == ["app/4", ""]
    assert found.reason_required


def test_a_joined_group_is_assessed_with_its_own_change() -> None:
    units = [
        target(joined=(Member(change="beta", groups=(2,)),)),
        stored_unit("beta/1", change="beta", groups=(2,), state=MERGED),
    ]

    found = assess("app/3", units)

    assert GroupFate(change="beta", group=2, carried_by="beta/1", merged=True) in found.groups


def test_the_dependents_that_have_not_finished_are_listed_with_their_states() -> None:
    units = [
        target(),
        unit("app/4", groups=(17,), depends_on=("app/3",)),
        unit("app/5", groups=(18,), depends_on=("app/3",), state=FAILED, branch="spec/app/5"),
        unit("app/6", groups=(19,), depends_on=("app/3",), state=MERGED),
        unit("app/7", groups=(20,)),
    ]

    found = assess("app/3", units)

    assert found.dependents == (
        Dependent(id="app/4", state="planned"),
        Dependent(id="app/5", state="failed"),
    )
