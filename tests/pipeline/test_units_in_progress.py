"""The limit on units in progress, and which ready unit a free slot goes to.

`ready_units` is the one place that answers what may start now, so the limit
and the ordering are read off what it returns. Both facts the rules need — a
pull request number and the branch a run recorded — are on the stored unit,
so these graphs are stored units and nothing asks the forge.
"""

from typing import Any

import pytest

from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    in_progress,
    project_counts,
    ready_units,
    start_room,
)
from tests.factories import requeued_unit, stored_unit
from tests.restack_lane_fakes import caused


def at_review(uid: str, pr: int, **kw):
    return stored_unit(uid, change=uid.split("/")[0], state=IN_REVIEW, pr=pr, **kw)


def new(uid: str, **kw):
    return stored_unit(uid, change=uid.split("/")[0], **kw)


def rework(uid: str, pr: int, **kw):
    return stored_unit(
        uid, change=uid.split("/")[0], state=PLANNED, pr=pr, feedback="use a Sequence", **kw
    )


def resuming(uid: str, **kw):
    """A build a run began and stopped: it has recorded its branch."""
    return stored_unit(uid, change=uid.split("/")[0], branch=f"spec/{uid}", **kw)


def failed(uid: str, **kw):
    return stored_unit(uid, change=uid.split("/")[0], state="failed", **kw)


def ready(graph, *, slots: int = 10, limit: int = 5, depth_cap: int = 10) -> list[str]:
    return [
        u.id
        for u in ready_units(
            graph, max_concurrent=slots, depth_cap=depth_cap, max_units_in_progress=limit
        )
    ]


# --- 1.1 what counts ---------------------------------------------------------------


def test_started_work_counts_as_in_progress() -> None:
    started = [
        stored_unit("a/1", change="a", state=RUNNING),
        at_review("b/1", 2),
        rework("e/1", 5),
        resuming("f/1"),
        stored_unit("g/1", change="g", state="unplanned", pr=7),
        stored_unit("h/1", change="h", state=RUNNING, pr=8),
    ]

    assert [in_progress(unit) for unit in started] == [True] * len(started)


def test_a_held_unit_does_not_count_whatever_it_holds() -> None:
    """Held is set aside until a person releases it — by a reviewer, the review
    loop or the operator — and should not keep new work from starting."""
    held = [
        stored_unit("a/1", change="a", state=HELD),
        stored_unit("b/1", change="b", state=HELD, pr=4),
        stored_unit("c/1", change="c", state=HELD, branch="spec/c/1"),
    ]

    assert [in_progress(unit) for unit in held] == [False] * len(held)


def test_a_held_unit_leaves_room_for_a_new_one() -> None:
    graph = [
        stored_unit("a/1", change="a", state=HELD, pr=4),
        at_review("b/1", 2),
        new("c/1"),
    ]

    started = ready_units(graph, max_concurrent=3, depth_cap=3, max_units_in_progress=2)

    assert [unit.id for unit in started] == ["c/1"]


def test_a_planned_unit_with_a_pull_request_but_no_resume_step_counts() -> None:
    assert in_progress(stored_unit("a/1", change="a", state=PLANNED, pr=3))


def test_finished_and_never_started_units_do_not_count() -> None:
    idle = [
        stored_unit("a/1", change="a", state=MERGED, pr=1),
        stored_unit("b/1", change="b", state=CLOSED, pr=2),
        stored_unit("c/1", change="c", state=SATISFIED, pr=3),
        stored_unit("d/1", change="d", state="unplanned"),
        new("e/1"),
        new("f/1", depends_on=("e/1",)),
    ]

    assert [in_progress(unit) for unit in idle] == [False] * len(idle)


def test_units_in_different_repositories_count_apart() -> None:
    graph = [at_review("a/1", 1, repo="app"), at_review("b/1", 2, repo="platform"), new("c/1")]

    assert ready(graph, limit=2) == ["c/1"]


# --- 1.2 at the limit a never-started unit does not start --------------------------


def test_a_ready_unit_is_not_started_at_the_limit() -> None:
    graph = [at_review("a/1", 1), at_review("b/1", 2), new("c/1")]

    assert ready(graph, limit=2) == []
    assert graph[2].state == PLANNED, "waiting, not failed or held"


def test_above_the_limit_still_holds_new_units() -> None:
    graph = [at_review("a/1", 1), at_review("b/1", 2), at_review("c/1", 3), new("d/1")]

    assert ready(graph, limit=2) == []


def test_a_unit_below_the_limit_starts() -> None:
    graph = [at_review("a/1", 1), new("b/1")]

    assert ready(graph, limit=2) == ["b/1"]


def test_only_as_many_new_units_start_as_fit_under_the_limit() -> None:
    graph = [at_review("a/1", 1), new("b/1"), new("c/1"), new("d/1")]

    assert ready(graph, limit=2) == ["b/1"]


def test_a_merge_makes_the_waiting_unit_startable() -> None:
    graph = [at_review("a/1", 1), at_review("b/1", 2), new("c/1")]
    assert ready(graph, limit=2) == []

    graph[0] = stored_unit("a/1", change="a", state=MERGED, pr=1)

    assert ready(graph, limit=2) == ["c/1"]


def test_below_the_limit_the_existing_rules_still_hold() -> None:
    """The limit adds a condition; it does not replace one."""
    graph = [at_review("a/1", 1), new("b/1", depends_on=("c/1",)), new("c/1")]

    assert ready(graph, limit=3) == ["c/1"]


def test_blocked_new_work_does_not_take_a_place() -> None:
    graph = [at_review("a/1", 1), new("b/1", depends_on=("c/1",)), new("c/1"), new("d/1")]

    assert ready(graph, limit=2, slots=1) == ["c/1"]


def test_a_running_build_with_no_pull_request_takes_a_place() -> None:
    graph = [at_review("a/1", 1), stored_unit("b/1", change="b", state=RUNNING), new("c/1")]

    assert ready(graph, limit=2) == []


# --- 1.3 work in progress is never blocked -----------------------------------------


def test_a_rework_starts_at_the_limit() -> None:
    graph = [at_review("a/1", 1), rework("b/1", 2)]

    assert ready(graph, limit=2) == ["b/1"]


def test_a_rework_starts_above_the_limit() -> None:
    graph = [at_review("a/1", 1), at_review("b/1", 2), rework("c/1", 3)]

    assert ready(graph, limit=1) == ["c/1"]


def test_a_resume_from_a_paused_build_starts_at_the_limit() -> None:
    graph = [at_review("a/1", 1), resuming("b/1"), new("c/1")]

    assert ready(graph, limit=2) == ["b/1"]


def test_a_resume_with_no_room_left_starts_above_the_limit() -> None:
    graph = [at_review("a/1", 1), at_review("b/1", 2), resuming("c/1")]

    assert ready(graph, limit=1) == ["c/1"]


def test_a_restacked_unit_with_a_pull_request_starts_at_the_limit() -> None:
    """A restack leaves the child planned, with its PR and branch."""
    graph = [
        at_review("a/1", 1),
        stored_unit("b/1", change="b", state=PLANNED, pr=2, branch="spec/b/1", feedback=""),
        new("c/1"),
    ]

    assert ready(graph, limit=2) == ["b/1"]


# --- 1.4 a paused unit holds a place, a failed unit holds none ---------------------


def test_three_started_units_one_failed_with_no_wait_and_a_limit_of_five_start_two_new_units() -> (
    None
):
    graph = [
        at_review("a/1", 1),
        at_review("b/1", 2),
        failed("c/1"),
        resuming("d/1"),
        new("n/1"),
        new("n/2"),
        new("n/3"),
    ]

    started = ready(graph, limit=5)

    assert [uid for uid in started if uid.startswith("n/")] == ["n/1", "n/2"]


def test_a_failed_unit_that_does_not_wait_holds_no_place() -> None:
    graph = [at_review("a/1", 1), failed("b/1"), new("c/1")]

    assert ready(graph, limit=2) == ["c/1"]


def test_a_paused_unit_with_no_pull_request_holds_a_place() -> None:
    graph = [at_review("a/1", 1), resuming("b/1"), new("c/1")]

    # b/1 holds the second place, so c/1 waits; b/1 itself may resume.
    assert ready(graph, limit=2) == ["b/1"]


# --- existing work first -----------------------------------------------------------


def test_a_rework_starts_ahead_of_an_earlier_planned_new_unit() -> None:
    graph = [new("a/1"), rework("b/1", 7)]

    assert ready(graph, slots=1) == ["b/1"]


def test_a_resuming_unit_starts_ahead_of_an_earlier_planned_new_unit() -> None:
    graph = [new("a/1"), resuming("b/1")]

    assert ready(graph, slots=1) == ["b/1"]


def test_a_rework_starts_ahead_of_a_resuming_unit() -> None:
    graph = [resuming("a/1"), rework("b/1", 7)]

    assert ready(graph, slots=1) == ["b/1"]


def test_with_room_for_all_three_they_are_returned_in_class_order() -> None:
    graph = [new("a/1"), resuming("b/1"), rework("c/1", 7)]

    assert ready(graph, slots=3) == ["c/1", "b/1", "a/1"]


def test_units_of_one_kind_start_in_the_order_they_were_planned() -> None:
    for make in (new, resuming):
        graph = [make("a/1"), make("b/1"), make("c/1")]
        assert ready(graph, slots=2, limit=10) == ["a/1", "b/1"]

    graph = [rework("a/1", 1), rework("b/1", 2), rework("c/1", 3)]
    assert ready(graph, slots=2, limit=10) == ["a/1", "b/1"]


def test_a_unit_with_a_pull_request_waiting_on_a_dependency_is_not_started() -> None:
    graph = [new("a/1"), rework("b/1", 7, depends_on=("a/1",)), new("c/1")]

    assert ready(graph, slots=1) == ["a/1"]
    assert "b/1" not in ready(graph, slots=3)


def test_a_unit_with_a_pull_request_past_the_depth_cap_is_not_started() -> None:
    graph = [
        at_review("a/1", 1),
        at_review("a/2", 2, depends_on=("a/1",)),
        rework("a/3", 3, depends_on=("a/2",)),
        new("b/1"),
    ]

    assert ready(graph, slots=1, depth_cap=2) == ["b/1"]


# --- a failed unit holds no place --------------------------------------------------

FAILED_WITH = {
    "nothing": {},
    "a branch": {"branch": "spec/f/1"},
    "a pushed commit": {"branch": "spec/f/1", "pushed": "abc123"},
    "a pull request": {"pr": 4, "branch": "spec/f/1"},
}


@pytest.mark.parametrize("held", FAILED_WITH.values(), ids=FAILED_WITH.keys())
def test_a_failed_unit_is_not_in_progress_whatever_it_has(held: dict) -> None:
    assert not in_progress(failed("f/1", **held))


def test_only_a_unit_failed_for_the_environment_is_in_progress() -> None:
    plain = failed("f/1", branch="spec/f/1")
    environment = caused("f/2", FAILED, Cause.ENVIRONMENT, branch="spec/f/2")

    assert (in_progress(plain), in_progress(environment)) == (False, True)


def test_a_failed_unit_with_a_pull_request_leaves_room_for_a_never_started_unit() -> None:
    graph = [at_review("a/1", 1), failed("b/1", pr=4, branch="spec/b/1"), new("c/1")]

    assert ready(graph, limit=2) == ["c/1"]


def test_a_unit_failed_for_the_environment_keeps_its_place_from_a_never_started_unit() -> None:
    def graph(beside_review):
        return [at_review("a/1", 1), beside_review, new("c/1")]

    environment = caused("b/1", FAILED, Cause.ENVIRONMENT, branch="spec/b/1")
    plain = failed("b/1", branch="spec/b/1")

    assert (ready(graph(environment), limit=2), ready(graph(plain), limit=2)) == ([], ["c/1"])


def test_a_planned_unit_depending_on_a_failed_unit_does_not_start() -> None:
    graph = [
        at_review("r/1", 1),
        failed("a/1"),
        new("b/1", depends_on=("a/1",)),
        new("c/1"),
    ]

    # The failed unit holds no place, so c/1 starts; b/1 still waits on it.
    assert ready(graph, limit=2) == ["c/1"]


# --- a unit requeued out of failed or held waits for room ---------------------------

# How the unit came back: out of which state, and the cause the requeue or release recorded.
COMES_BACK: dict[str, dict[str, Any]] = {
    "failed": dict(out_of="failed"),
    "held": dict(out_of="held"),
    "released": dict(out_of="held", cause=Cause.RELEASED),
}


def comes_back(uid: str, kind: str, **kw):
    return requeued_unit(uid, **COMES_BACK[kind], **kw)


@pytest.mark.parametrize("pr", [None, 3])
@pytest.mark.parametrize("kind", COMES_BACK)
def test_a_unit_requeued_out_of_failed_or_held_does_not_start_at_a_full_limit(
    kind: str, pr: int | None
) -> None:
    graph = [at_review("a/1", 1), at_review("b/1", 2), comes_back("c/1", kind, pr=pr)]

    assert ready(graph, limit=2) == []


@pytest.mark.parametrize("pr", [None, 3])
@pytest.mark.parametrize("kind", COMES_BACK)
def test_a_unit_waiting_for_room_after_a_requeue_is_not_counted(kind: str, pr: int | None) -> None:
    graph = [at_review("a/1", 1), comes_back("c/1", kind, pr=pr)]

    assert sum(project_counts(graph).values()) == 1
    assert start_room(graph, 2) == 1


@pytest.mark.parametrize("kind", COMES_BACK)
def test_a_unit_waiting_for_room_after_a_requeue_is_not_counted_in_an_account(kind: str) -> None:
    graph = [at_review("a/1", 1), comes_back("c/1", kind)]

    assert project_counts(graph, lambda unit: "account") == {"account": 1}
    assert start_room(graph, 2, "account", lambda unit: "account") == 1


@pytest.mark.parametrize("kind", COMES_BACK)
def test_a_requeued_unit_takes_the_place_that_frees_before_a_never_started_unit(
    kind: str,
) -> None:
    graph = [new("n/1"), at_review("a/1", 1), comes_back("c/1", kind)]

    # The requeued unit waits for room and so is not counted: one place is free for it.
    assert start_room(graph, 2) == 1
    assert ready(graph, limit=2) == ["c/1"]


@pytest.mark.parametrize("kind", COMES_BACK)
def test_a_requeued_priority_zero_unit_starts_in_the_emergency_lane_at_a_full_limit(
    kind: str,
) -> None:
    graph = [at_review("a/1", 1), at_review("b/1", 2), comes_back("c/1", kind, priority=0)]

    def lane_starts(extra: int) -> list[str]:
        return [
            unit.id
            for unit in ready_units(
                graph,
                max_concurrent=9,
                depth_cap=9,
                max_units_in_progress=2,
                emergency_extra=extra,
            )
        ]

    assert (lane_starts(1), lane_starts(0)) == (["c/1"], [])


KEPT_ITS_PLACE: dict[str, dict[str, Any]] = {
    "a running unit no run holds": dict(out_of="running"),
    "a unit off a split park": dict(out_of="planned", before=Cause.SPLIT_HELD),
}


@pytest.mark.parametrize("kept", KEPT_ITS_PLACE.values(), ids=KEPT_ITS_PLACE.keys())
def test_a_unit_that_kept_its_place_starts_at_a_full_limit_and_one_out_of_failed_does_not(
    kept: dict,
) -> None:
    graph = [
        at_review("a/1", 1),
        at_review("b/1", 2),
        requeued_unit("c/1", **kept),
        comes_back("d/1", "failed"),
    ]

    assert ready(graph, limit=2) == ["c/1"]
