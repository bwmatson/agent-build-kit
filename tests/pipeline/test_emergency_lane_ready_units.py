"""A ready priority-0 unit starts past the normal limits in the emergency lane, with a cap of its
own (`emergency_extra`); every other unit keeps the normal limits.

The project is full when `max_units_in_progress` 5 and `max_concurrent` 4 are both reached: four
units running and one in review. `in_lane` names the units already using the lane."""

from __future__ import annotations

from collections.abc import Collection, Sequence

import pytest

from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED, RUNNING, ready_units
from tests.factories import new_unit as new
from tests.factories import worked_unit as worked
from tests.restack_lane_fakes import caused

PLACES = 5
WORKERS = 4


def starts(
    graph: Sequence[StoredUnit],
    *,
    extra: int = 1,
    lane: Collection[str] = (),
    excluded: Collection[str] = (),
    depth_cap: int = 9,
) -> list[str]:
    """The ids `ready_units` starts at `PLACES` places and `WORKERS` workers."""
    return [
        unit.id
        for unit in ready_units(
            graph,
            max_concurrent=WORKERS,
            depth_cap=depth_cap,
            max_units_in_progress=PLACES,
            excluded=excluded,
            emergency_extra=extra,
            in_lane=lane,
        )
    ]


def in_project(project: str | None) -> dict[str, str]:
    return {} if project is None else {"project": project}


def running(count: int, project: str | None = None, prefix: str = "run") -> list[StoredUnit]:
    return [worked(f"{prefix}{n}/1", state=RUNNING, **in_project(project)) for n in range(count)]


def reviewing(count: int, project: str | None = None, prefix: str = "rev") -> list[StoredUnit]:
    return [
        worked(f"{prefix}{n}/1", state=IN_REVIEW, pr=n + 1, **in_project(project))
        for n in range(count)
    ]


def full(project: str | None = None, prefix: str = "") -> list[StoredUnit]:
    """Five in progress, four of them running."""
    return [
        *running(4, project, f"{prefix}run"),
        *reviewing(1, project, f"{prefix}rev"),
    ]


# --- 2.1 the rule ---------------------------------------------------------------------------


def test_a_ready_priority_zero_unit_starts_at_a_full_project_and_a_priority_one_unit_does_not() -> (
    None
):
    graph = [*full(), new("one/1", priority=1), new("zero/1", priority=0)]

    assert starts(graph) == ["zero/1"]


def test_two_ready_priority_zero_units_start_one_and_the_other_waits() -> None:
    graph = [*full(), new("zero/1", priority=0), new("zero/2", priority=0)]

    assert starts(graph) == ["zero/1"]


def test_a_lane_cap_of_zero_or_none_given_starts_nothing_past_the_limits() -> None:
    graph = [*full(), new("zero/1", priority=0)]

    assert starts(graph, extra=1) == ["zero/1"]
    assert starts(graph, extra=0) == []
    assert (
        ready_units(graph, max_concurrent=WORKERS, depth_cap=9, max_units_in_progress=PLACES) == []
    )


def test_a_prerequisite_of_a_priority_zero_unit_uses_the_lane_and_the_waiter_does_not() -> None:
    graph = [*full(), new("base/1"), new("top/1", priority=0, depends_on=("base/1",))]

    assert starts(graph) == ["base/1"]


def test_a_waiter_the_round_leaves_out_lends_nothing_to_its_prerequisite() -> None:
    graph = [*full(), new("base/1"), new("top/1", priority=0, depends_on=("base/1",))]

    assert starts(graph) == ["base/1"]
    assert starts(graph, excluded={"top/1"}) == []


# --- 2.2 the cap ----------------------------------------------------------------------------


def test_the_first_unit_inside_the_limits_is_normal_and_the_second_takes_the_lane() -> None:
    graph = [
        *reviewing(3),
        *running(1),
        new("zero/1", priority=0),
        new("zero/2", priority=0),
        new("zero/3", priority=0),
    ]

    assert starts(graph) == ["zero/1", "zero/2"]

    now_running = [
        *reviewing(3),
        *running(1),
        worked("zero/1", state=RUNNING, priority=0),
        worked("zero/2", state=RUNNING, priority=0),
        new("zero/3", priority=0),
    ]
    assert starts(now_running, lane=["zero/2"]) == []
    assert starts(now_running, lane=["zero/2"], extra=2) == ["zero/3"]


def test_a_lane_unit_holds_the_use_at_one_after_a_normal_place_frees_and_until_it_finishes() -> (
    None
):
    lane_unit = worked("lane/1", state=RUNNING, priority=0)
    waiting = new("zero/2", priority=0)
    graph = [*full(), lane_unit, waiting]

    assert starts(graph, lane=["lane/1"]) == []

    freed = [*graph[:3], worked("run3/1", state=MERGED), *graph[4:]]
    assert starts(freed, lane=["lane/1"]) == []

    finished = [*full(), worked("lane/1", state=MERGED, priority=0), waiting]
    assert starts(finished, lane=["lane/1"]) == ["zero/2"]


def test_each_full_project_has_its_own_lane_use() -> None:
    graph = [
        *full("web", "web-"),
        worked("lane/1", state=RUNNING, priority=0, project="web"),
        new("web-zero/1", priority=0, project="web"),
        *full("api", "api-"),
        new("api-zero/1", priority=0, project="api"),
    ]

    assert starts(graph, lane=["lane/1"]) == ["api-zero/1"]


def test_a_free_place_with_the_workers_full_still_starts_a_priority_zero_unit_in_the_lane() -> None:
    graph = [*running(4), new("zero/1", priority=0), new("zero/2", priority=0)]

    assert starts(graph) == ["zero/1"]
    assert starts(graph, extra=0) == []


def test_a_free_worker_with_the_places_full_still_starts_a_priority_zero_unit_in_the_lane() -> None:
    graph = [*running(3), *reviewing(2), new("zero/1", priority=0), new("zero/2", priority=0)]

    assert starts(graph) == ["zero/1"]
    assert starts(graph, extra=0) == []


def test_a_finished_unit_left_in_the_lane_record_uses_no_cap() -> None:
    graph = [*full(), worked("gone/1", state=MERGED, priority=0), new("zero/1", priority=0)]

    assert starts(graph, lane=["gone/1"]) == ["zero/1"]
    assert starts(graph, lane=["unknown/1"]) == ["zero/1"]


# --- 2.3 units already started --------------------------------------------------------------


def test_a_priority_zero_rework_starts_at_the_limit_and_leaves_the_lane_cap_to_a_new_unit() -> None:
    rework = worked("rework/1", state=PLANNED, pr=9, feedback="rework", priority=0)
    graph = [*running(3), *reviewing(1), rework, new("zero/1", priority=0)]

    assert starts(graph) == ["rework/1", "zero/1"]
    assert starts(graph, extra=0) == ["rework/1"]


def test_a_paused_priority_zero_unit_waits_for_a_worker_and_does_not_use_the_lane() -> None:
    paused = worked("paused/1", state=PLANNED, priority=0)
    graph = [*running(4), paused, new("zero/1", priority=0)]

    assert starts(graph) == ["zero/1"]


def test_a_blocked_priority_zero_unit_is_not_chosen_and_counts_nothing() -> None:
    blocked = worked("blocked/1", state=PLANNED, priority=0, depends_on=("run0/1",))
    graph = [
        *reviewing(3),
        *running(1),
        blocked,
        new("zero/1", priority=0),
        new("zero/2", priority=0),
    ]

    assert starts(graph) == ["zero/1", "zero/2"]


def test_a_unit_that_was_blocked_and_waits_for_room_draws_on_the_lane_like_a_new_one() -> None:
    waiting = caused("waiting/1", PLANNED, Cause.GATED, branch="spec/waiting/1", priority=0)
    graph = [*running(4), waiting]

    assert starts(graph) == ["waiting/1"]
    assert starts(graph, extra=0) == []


def test_a_priority_zero_unit_beyond_the_depth_cap_is_not_chosen() -> None:
    graph = [*full(), new("deep/1", priority=0, depends_on=("rev0/1",))]

    assert starts(graph, depth_cap=2) == ["deep/1"]
    assert starts(graph, depth_cap=1) == []


@pytest.mark.parametrize("state", ["held", "failed"])
def test_a_priority_zero_unit_the_round_holds_back_is_not_chosen(state: str) -> None:
    graph = [*full(), new("zero/1", priority=0)]
    assert starts(graph) == ["zero/1"]

    held = [*full(), new("zero/1", priority=0, state=state)]

    assert starts(held, excluded={"zero/1"}) == []
