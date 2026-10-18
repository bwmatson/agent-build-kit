"""A retired unit is finished: it is not in progress, takes no place, nothing waits on it, and
nothing counts its groups as a later unit's (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    UnitState,
    blocked,
    earlier_units,
    in_progress,
    later_groups,
    start_room,
    waiting_on,
)
from tests.factories import new_unit as new
from tests.factories import started_ids
from tests.factories import worked_unit as worked

RETIRED = UnitState.RETIRED


def retired(uid: str, **overrides):
    """A retired unit that still has the branch it was built on."""
    return worked(uid, state=RETIRED, **overrides)


def test_a_retired_unit_with_a_branch_is_not_in_progress_and_takes_no_place() -> None:
    counted = [new(f"c{n}/1", state=IN_REVIEW, pr=n) for n in range(1, 5)]
    gone = retired("gone/1")
    graph = [*counted, gone]

    assert not in_progress(gone, graph)
    assert start_room(graph, 5) == 1


@pytest.mark.parametrize("repo", ["app", "platform"], ids=["same repo", "other repo"])
def test_a_dependent_of_a_retired_unit_is_not_waiting(repo: str) -> None:
    graph = [retired("gone/1", repo=repo), worked("next/1", depends_on=("gone/1",))]

    assert waiting_on(graph[1], graph) == []
    assert not blocked(graph[1], graph)


def test_a_dependent_of_a_retired_unit_starts_when_the_rules_allow() -> None:
    graph = [retired("gone/1"), new("next/1", depends_on=("gone/1",))]

    assert started_ids(graph, max_units_in_progress=5) == ["next/1"]


def test_an_acceptance_unit_does_not_follow_a_retired_unit_of_its_change() -> None:
    graph = [
        retired("feat/1"),
        new("feat/2"),
        new("feat/3", flag="acceptance"),
    ]

    assert [unit.id for unit in earlier_units(graph[2], graph)] == ["feat/2"]


def test_the_groups_of_a_retired_unit_are_not_later_work() -> None:
    graph = [
        new("feat/1", groups=(1,)),
        retired("feat/2", groups=(2,)),
        new("feat/3", groups=(3,)),
    ]

    assert later_groups(graph[0], graph) == (3,)
