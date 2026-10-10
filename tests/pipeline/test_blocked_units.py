"""A blocked unit holds no place, and the unit blocking it takes its place first.

A planned unit that waits on another unit is not counted in progress however
much work it has. These graphs are stored units, so nothing asks the forge.
"""

import pytest

from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    blocked,
    ready_units,
    start_room,
)
from agent_build_kit.pipeline.vocabulary import effective_state
from tests.factories import new_unit as new


def caused(cause: Cause) -> dict:
    """The history a state change records, which is where a unit's cause is read from."""
    return {"history": ({"state": "planned", "at": "2026-09-23T09:00", "cause": cause.value},)}


def worked(uid: str, **kw):
    """A planned unit a run began and stopped: it has recorded its branch."""
    return new(uid, branch=f"spec/{uid}", **kw)


def review(uid: str, pr: int = 1, **kw):
    return new(uid, state=IN_REVIEW, pr=pr, **kw)


def chosen(graph, *, slots: int = 9, limit: int = 9, excluded=frozenset()) -> list[str]:
    return [
        unit.id
        for unit in ready_units(
            graph,
            max_concurrent=slots,
            depth_cap=9,
            max_units_in_progress=limit,
            excluded=excluded,
        )
    ]


# --- 1.1 what is blocked, and what counts -------------------------------------------


@pytest.mark.parametrize("prerequisite", [PLANNED, RUNNING, FAILED, HELD])
def test_a_unit_waiting_on_a_prerequisite_that_has_not_been_reviewed_is_blocked(
    prerequisite: str,
) -> None:
    graph = [new("base/1", state=prerequisite), worked("next/1", depends_on=("base/1",))]

    assert blocked(graph[1], graph)


def test_a_unit_waiting_on_a_predecessor_being_reworked_is_blocked() -> None:
    graph = [
        new("base/1", state=PLANNED, pr=4, feedback="use a Sequence"),
        worked("next/1", depends_on=("base/1",)),
    ]

    assert blocked(graph[1], graph)


def test_a_unit_waiting_on_a_cross_repo_prerequisite_that_has_not_merged_is_blocked() -> None:
    graph = [
        review("base/1", repo="platform"),
        worked("next/1", depends_on=("base/1",)),
    ]

    assert blocked(graph[1], graph)


@pytest.mark.parametrize("cause", [Cause.GATED, Cause.UPSTREAM_WENT_BACK])
def test_the_causes_gated_and_upstream_went_back_make_a_unit_blocked(cause: Cause) -> None:
    unit = worked("one/1", **caused(cause))

    assert blocked(unit, [unit])


def test_a_unit_whose_prerequisite_is_in_review_or_merged_is_not_blocked() -> None:
    graph = [
        review("base/1"),
        new("done/1", state=MERGED, repo="platform"),
        worked("next/1", depends_on=("base/1", "done/1")),
    ]

    assert not blocked(graph[2], graph)


@pytest.mark.parametrize("cause", [Cause.USAGE, Cause.HOST_UNAVAILABLE])
def test_a_usage_pause_and_a_host_backoff_do_not_make_a_unit_blocked(cause: Cause) -> None:
    unit = worked("one/1", **caused(cause))

    assert not blocked(unit, [unit])


def test_a_blocked_unit_with_work_does_not_count_toward_the_limit() -> None:
    graph = [
        new("base/1", state=RUNNING),
        worked("next/1", depends_on=("base/1",)),
    ]

    assert start_room(graph, 2) == 1


def test_a_unit_no_longer_blocked_counts_again() -> None:
    graph = [review("base/1"), worked("next/1", depends_on=("base/1",))]

    assert start_room(graph, 2) == 0


def test_running_review_and_failed_units_count_and_a_held_unit_does_not() -> None:
    graph = [
        new("a/1", state=RUNNING),
        review("b/1"),
        new("c/1", state=FAILED),
        new("d/1", state=HELD, branch="spec/d/1"),
    ]

    assert start_room(graph, 5) == 2


def test_a_unit_left_out_of_a_limited_tick_is_not_blocked_by_that() -> None:
    graph = [worked("one/1"), new("other/1")]

    assert not blocked(graph[0], graph)
    assert start_room(graph, 1) == 0


# --- 1.2 the handoff ---------------------------------------------------------------


def test_a_ready_prerequisite_takes_the_place_of_the_blocked_unit_at_the_limit() -> None:
    graph = [
        new("older/1"),
        review("busy/1"),
        worked("blocked/1", depends_on=("base/1",)),
        new("base/1"),
    ]

    assert chosen(graph, limit=2) == ["base/1"]


def test_the_handoff_comes_ahead_of_work_resuming_a_build() -> None:
    graph = [
        review("busy/1"),
        worked("paused/1"),
        worked("blocked/1", depends_on=("base/1",)),
        new("base/1"),
    ]

    assert chosen(graph, limit=3, slots=1)[0] == "base/1"


def test_the_prerequisite_of_a_unit_that_never_started_gets_no_handoff() -> None:
    graph = [
        review("one/1"),
        review("two/1", pr=2),
        new("waiter/1", depends_on=("base/1",)),
        new("base/1"),
    ]

    assert chosen(graph, limit=2) == []


def test_two_blocked_units_on_one_prerequisite_give_it_one_place() -> None:
    graph = [
        review("busy/1"),
        worked("one/1", depends_on=("base/1",)),
        worked("two/1", depends_on=("base/1",)),
        new("base/1"),
        new("next/1"),
        new("last/1"),
    ]

    assert chosen(graph, limit=3) == ["base/1", "next/1"]


def test_several_prerequisites_are_ordered_by_effective_priority() -> None:
    graph = [
        worked("one/1", depends_on=("first/1",)),
        worked("two/1", depends_on=("second/1",), priority=1),
        new("first/1"),
        new("second/1"),
    ]

    assert chosen(graph, limit=2, slots=1) == ["second/1"]


def test_equal_priorities_are_ordered_by_effective_age() -> None:
    graph = [
        worked("one/1", depends_on=("first/1",)),
        worked("two/1", depends_on=("second/1",)),
        new("second/1"),
        new("first/1"),
    ]

    assert chosen(graph, limit=2, slots=1) == ["first/1"]


def test_the_handoff_does_not_pass_the_cap_on_units_running_at_once() -> None:
    graph = [
        new("run/1", state=RUNNING),
        review("busy/1"),
        worked("blocked/1", depends_on=("base/1",)),
        new("base/1"),
    ]

    assert chosen(graph, limit=3, slots=1) == []


def test_the_handoff_skips_a_prerequisite_the_round_leaves_out() -> None:
    graph = [
        review("busy/1"),
        worked("blocked/1", depends_on=("base/1",)),
        new("base/1"),
        new("next/1"),
    ]

    assert "base/1" not in chosen(graph, limit=2, excluded={"base/1"})


# --- 1.3 an unblocked unit waits for room ------------------------------------------


def unblocked_graph(*, busy: int):
    return [
        *(review(f"busy{n}/1", pr=n + 1) for n in range(busy)),
        new("base/1", state=MERGED, repo="platform"),
        worked("back/1", depends_on=("base/1",)),
    ]


def test_a_unit_no_longer_blocked_stays_planned_while_the_others_fill_the_limit() -> None:
    assert chosen(unblocked_graph(busy=2), limit=2) == []


def test_a_unit_no_longer_blocked_starts_when_one_finishes() -> None:
    assert chosen(unblocked_graph(busy=1), limit=2) == ["back/1"]


def test_a_unit_paused_by_a_usage_pause_resumes_at_the_limit() -> None:
    graph = [review("busy/1"), review("busy/2", pr=2), worked("paused/1", **caused(Cause.USAGE))]

    assert chosen(graph, limit=2) == ["paused/1"]


def test_a_rework_proceeds_at_the_limit() -> None:
    graph = [
        review("busy/1"),
        new("again/1", state=PLANNED, pr=5, feedback="use a Sequence", **caused(Cause.REWORK)),
    ]

    assert chosen(graph, limit=2) == ["again/1"]


# --- 1.4 the graph ------------------------------------------------------------------


def test_the_graph_labels_a_gated_unit_as_blocked() -> None:
    unit = worked("one/1", **caused(Cause.GATED))

    assert effective_state(unit, [unit]) == "blocked"
