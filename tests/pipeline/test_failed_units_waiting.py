"""A failed unit that waits on another unit holds no place, and counts again,
still failed, once the wait ends.

The wait is whatever `waiting_on` says. These graphs are stored units, so
nothing asks the forge, and none names `merge_before` or `unmet_gates`.
"""

import pytest

from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    failed_waiting,
    failed_waiting_units,
    in_progress,
    ready_units,
    start_room,
)
from tests.factories import new_unit as new


def review(uid: str, pr: int = 1, **kw):
    return new(uid, state=IN_REVIEW, pr=pr, **kw)


def worked(uid: str, **kw):
    """A planned unit a run began and stopped: it has recorded its branch."""
    return new(uid, branch=f"spec/{uid}", **kw)


def reworked(uid: str, pr: int, **kw):
    return new(uid, state=PLANNED, pr=pr, feedback="use a Sequence", **kw)


def waiter(**kw):
    return new("next/1", state=FAILED, branch="spec/next/1", depends_on=("base/1",), **kw)


def entry(state: str, hour: int) -> dict:
    return dict(state=state, at=f"2026-09-23T{hour:02d}:00:00+00:00")


def chosen(graph, *, slots: int = 9, limit: int = 9, depth_cap: int = 9) -> list[str]:
    return [
        unit.id
        for unit in ready_units(
            graph, max_concurrent=slots, depth_cap=depth_cap, max_units_in_progress=limit
        )
    ]


# --- 1.1 which failed units wait, and what counts -----------------------------------


@pytest.mark.parametrize("prerequisite", [PLANNED, RUNNING, FAILED, HELD])
def test_a_failed_unit_whose_predecessor_is_not_yet_reviewed_does_not_count(
    prerequisite: str,
) -> None:
    graph = [new("base/1", state=prerequisite), waiter()]

    assert failed_waiting(graph[1], graph)
    assert not in_progress(graph[1], graph)


def test_a_failed_unit_whose_predecessor_is_being_reworked_does_not_count() -> None:
    graph = [reworked("base/1", 4), waiter()]

    assert failed_waiting(graph[1], graph)
    assert not in_progress(graph[1], graph)


def test_a_failed_unit_whose_cross_repo_dependency_has_not_merged_does_not_count() -> None:
    graph = [review("base/1", repo="platform"), waiter()]

    assert failed_waiting(graph[1], graph)
    assert not in_progress(graph[1], graph)


@pytest.mark.parametrize("merged", [False, True], ids=["in review", "merged"])
def test_a_failed_unit_whose_predecessor_is_in_review_or_merged_counts(merged: bool) -> None:
    ahead = new("base/1", state=MERGED, pr=1) if merged else review("base/1")
    graph = [ahead, waiter()]

    assert not failed_waiting(graph[1], graph)
    assert in_progress(graph[1], graph)


def test_a_failed_unit_with_no_dependency_counts() -> None:
    unit = new("alone/1", state=FAILED)

    assert not failed_waiting(unit, [unit])
    assert in_progress(unit, [unit])


@pytest.mark.parametrize("prerequisite", [PLANNED, RUNNING, FAILED, HELD])
def test_a_waiting_failed_unit_raises_the_room_by_one(prerequisite: str) -> None:
    ahead = new("base/1", state=prerequisite)
    waiting = [ahead, waiter()]
    free = [ahead, new("next/1", state=FAILED, branch="spec/next/1")]

    assert start_room(waiting, 5) == start_room(free, 5) + 1
    assert start_room(waiting, 5) == start_room([ahead], 5)


def test_the_room_rises_for_every_waiting_failed_unit() -> None:
    base = new("base/1", state=RUNNING)
    two = [base, waiter(), new("also/1", state=FAILED, depends_on=("base/1",))]
    plain = [base, new("next/1", state=FAILED), new("also/1", state=FAILED)]

    assert start_room(two, 6) == start_room(plain, 6) + 2
    assert failed_waiting_units(two) == [two[1], two[2]]


# --- 1.2 the wait ends -------------------------------------------------------------


def test_a_failed_unit_counts_again_still_failed_once_the_prerequisite_is_reviewed() -> None:
    unit = waiter()
    assert not in_progress(unit, [new("base/1", state=RUNNING), unit])

    reviewed = [review("base/1"), unit]

    assert in_progress(unit, reviewed)
    assert not failed_waiting(unit, reviewed)
    assert unit.state == FAILED
    assert unit == waiter()
    assert chosen(reviewed) == []


def test_a_failed_unit_counts_again_when_the_prerequisite_merges() -> None:
    unit = waiter()
    assert not in_progress(unit, [review("base/1", repo="platform"), unit])

    merged = [new("base/1", state=MERGED, repo="platform", pr=1), unit]

    assert in_progress(unit, merged)
    assert unit.state == FAILED
    assert chosen(merged) == []


# --- 1.3 at the limit --------------------------------------------------------------


def test_a_planned_unit_that_never_started_starts_into_the_place_a_waiting_failed_unit_left() -> (
    None
):
    graph = [review("a/1"), new("base/1", state=RUNNING), waiter(), new("n/1")]

    assert chosen(graph, limit=3) == ["n/1"]


def test_when_the_wait_ends_work_in_progress_proceeds_over_the_limit_and_nothing_new_starts() -> (
    None
):
    graph = [
        review("a/1"),
        new("base/1", state=RUNNING),
        waiter(),
        reworked("r/1", 5),
        worked("s/1"),
        new("t/1", state=PLANNED, pr=6, branch="spec/t/1", feedback=""),
        new("n/1"),
    ]
    assert not in_progress(graph[2], graph)
    assert "n/1" in chosen(graph, limit=6)

    ended = [graph[0], review("base/1", pr=2), *graph[2:]]

    started = chosen(ended, limit=3)
    assert in_progress(ended[2], ended)
    assert "next/1" not in started
    assert "n/1" not in started
    assert set(started) == {"r/1", "s/1", "t/1"}


def test_a_planned_unit_no_longer_blocked_stays_planned_until_the_count_is_below_the_limit() -> (
    None
):
    back = worked("back/1", depends_on=("p/1",), history=(entry("planned", 10),))
    returned = review(
        "p/1",
        pr=3,
        history=(entry("in_review", 8), entry("planned", 11), entry("in_review", 12)),
    )
    graph = [
        review("busy/1"),
        returned,
        back,
        new("q/1", state=RUNNING),
        new("next/1", state=FAILED, depends_on=("q/1",)),
    ]
    assert chosen(graph, limit=4) == ["back/1"]

    ended = [*graph[:3], review("q/1", pr=2), graph[4]]

    assert chosen(ended, limit=4) == []
    assert chosen(ended, limit=5) == ["back/1"]


# --- 1.4 the caps and the handoff --------------------------------------------------


def test_the_caps_choose_the_same_units_with_a_waiting_failed_unit_in_the_graph() -> None:
    base = [
        review("x/1"),
        review("x/2", pr=2, depends_on=("x/1",)),
        new("x/3", depends_on=("x/2",)),
        new("y/1"),
        new("z/1"),
        new("run/1", state=RUNNING),
    ]
    extra = new("w/1", state=FAILED, depends_on=("run/1",))

    assert failed_waiting(extra, [*base, extra])
    for slots, depth_cap in [(1, 9), (2, 9), (3, 2), (9, 1)]:
        assert chosen([*base, extra], slots=slots, depth_cap=depth_cap) == chosen(
            base, slots=slots, depth_cap=depth_cap
        )


def test_a_held_unit_does_not_count_whether_or_not_it_waits() -> None:
    graph = [
        new("run/1", state=RUNNING),
        new("waits/1", state=HELD, branch="spec/waits/1", depends_on=("run/1",)),
        new("free/1", state=HELD, branch="spec/free/1"),
    ]

    assert not in_progress(graph[1], graph)
    assert not in_progress(graph[2], graph)
    assert failed_waiting_units(graph) == []


def test_a_ready_prerequisite_of_a_waiting_failed_unit_gets_no_handoff() -> None:
    graph = [review("busy/1"), new("older/1"), waiter(), new("base/1")]

    assert chosen(graph, limit=2) == ["older/1"]


def test_a_blocked_planned_units_prerequisite_still_gets_the_handoff() -> None:
    graph = [
        review("busy/1"),
        new("older/1"),
        worked("blocked/1", depends_on=("base/1",)),
        new("base/1"),
    ]

    assert chosen(graph, limit=2) == ["base/1"]
    assert failed_waiting_units(graph) == []
