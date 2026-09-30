"""The ceiling on open pull requests, and which ready unit a free slot goes to.

`ready_units` is the one place that answers what may start now, so the ceiling
and the ordering are read off what it returns. Both facts the ordering needs —
a pull request number and the step a unit resumes from — are on the stored
unit, so these graphs are stored units and nothing asks the forge.
"""

from agent_build_kit.pipeline.units import (
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    open_pr_count,
    ready_units,
)
from tests.factories import stored_unit


def at_review(uid: str, pr: int, **kw):
    return stored_unit(uid, change=uid.split("/")[0], state=IN_REVIEW, pr=pr, **kw)


def new(uid: str, **kw):
    return stored_unit(uid, change=uid.split("/")[0], **kw)


def rework(uid: str, pr: int, **kw):
    return stored_unit(
        uid, change=uid.split("/")[0], state=PLANNED, pr=pr, feedback="use a Sequence", **kw
    )


def resuming(uid: str, **kw):
    return stored_unit(uid, change=uid.split("/")[0], resume_from="implement", **kw)


def ready(graph, *, slots: int = 10, ceiling: int = 5, depth_cap: int = 10) -> list[str]:
    return [
        u.id
        for u in ready_units(graph, max_concurrent=slots, depth_cap=depth_cap, max_open_prs=ceiling)
    ]


# --- 1.1 what counts ---------------------------------------------------------------


def test_open_pull_requests_in_different_repositories_count_together() -> None:
    graph = [at_review("a/1", 1, repo="app"), at_review("b/1", 2, repo="platform")]

    assert open_pr_count(graph) == 2


def test_a_pull_request_open_while_its_unit_is_reworked_counts() -> None:
    graph = [at_review("a/1", 1), rework("b/1", 2)]

    assert open_pr_count(graph) == 2


def test_a_running_or_held_unit_with_a_pull_request_counts() -> None:
    graph = [
        stored_unit("a/1", change="a", state=RUNNING, pr=1),
        stored_unit("b/1", change="b", state=HELD, pr=2),
    ]

    assert open_pr_count(graph) == 2


def test_merged_closed_and_unopened_units_do_not_count() -> None:
    graph = [
        at_review("a/1", 1),
        stored_unit("b/1", change="b", state=MERGED, pr=2),
        stored_unit("c/1", change="c", state="closed", pr=3),
        new("d/1"),
        resuming("e/1"),
    ]

    assert open_pr_count(graph) == 1


# --- 1.2 at the ceiling nothing new starts -----------------------------------------


def test_a_ready_unit_is_not_started_at_the_ceiling() -> None:
    graph = [at_review("a/1", 1), at_review("b/1", 2), new("c/1")]

    assert ready(graph, ceiling=2) == []
    assert graph[2].state == PLANNED, "waiting, not failed or held"


def test_the_ceiling_counts_across_repositories() -> None:
    graph = [at_review("a/1", 1, repo="app"), at_review("b/1", 2, repo="platform"), new("c/1")]

    assert ready(graph, ceiling=2) == []


def test_above_the_ceiling_still_holds_new_units() -> None:
    graph = [at_review("a/1", 1), at_review("b/1", 2), at_review("c/1", 3), new("d/1")]

    assert ready(graph, ceiling=2) == []


def test_a_unit_below_the_ceiling_starts() -> None:
    graph = [at_review("a/1", 1), new("b/1")]

    assert ready(graph, ceiling=2) == ["b/1"]


def test_a_merge_makes_the_waiting_unit_startable() -> None:
    graph = [at_review("a/1", 1), at_review("b/1", 2), new("c/1")]
    assert ready(graph, ceiling=2) == []

    graph[0] = stored_unit("a/1", change="a", state=MERGED, pr=1)

    assert ready(graph, ceiling=2) == ["c/1"]


def test_below_the_ceiling_the_existing_rules_still_hold() -> None:
    """The ceiling adds a condition; it does not replace one."""
    graph = [at_review("a/1", 1), new("b/1", depends_on=("c/1",)), new("c/1")]

    assert ready(graph, ceiling=3) == ["c/1"]


# --- 1.2 a new start must leave room for the pull requests still to come ----------


def test_only_as_many_new_units_start_as_fit_under_the_ceiling() -> None:
    graph = [at_review("a/1", 1), new("b/1"), new("c/1"), new("d/1")]

    assert ready(graph, ceiling=2, slots=10) == ["b/1"]


def test_a_build_still_heading_for_a_pull_request_takes_the_room() -> None:
    graph = [
        at_review("a/1", 1),
        stored_unit("b/1", change="b", state=RUNNING),
        new("c/1"),
        rework("d/1", 4),
    ]

    assert ready(graph, ceiling=2) == ["d/1"]


def test_room_is_shared_by_resuming_and_new_units_in_start_order() -> None:
    graph = [at_review("a/1", 1), new("b/1"), resuming("c/1")]

    assert ready(graph, ceiling=2) == ["c/1"]


# --- 1.3 draining is never blocked -------------------------------------------------


def test_a_rework_starts_at_the_ceiling() -> None:
    graph = [at_review("a/1", 1), rework("b/1", 2)]

    assert ready(graph, ceiling=2) == ["b/1"]


def test_a_rework_starts_above_the_ceiling() -> None:
    graph = [at_review("a/1", 1), at_review("b/1", 2), rework("c/1", 3)]

    assert ready(graph, ceiling=1) == ["c/1"]


def test_a_restacked_unit_with_a_pull_request_starts_at_the_ceiling() -> None:
    """A restack leaves the child planned, with its PR and a step to resume from."""
    graph = [
        at_review("a/1", 1),
        stored_unit(
            "b/1", change="b", state=PLANNED, pr=2, resume_from="rework_review", feedback=""
        ),
        new("c/1"),
    ]

    assert ready(graph, ceiling=2) == ["b/1"]


def test_a_restacked_unit_starts_ahead_of_an_earlier_resuming_unit() -> None:
    graph = [
        resuming("a/1"),
        stored_unit("b/1", change="b", state=PLANNED, pr=2, resume_from="rework_review"),
    ]

    assert ready(graph, slots=1) == ["b/1"]


# --- 1.5 existing work first -------------------------------------------------------


def test_a_rework_starts_ahead_of_an_earlier_planned_new_unit() -> None:
    graph = [new("a/1"), rework("b/1", 7)]

    assert ready(graph, slots=1) == ["b/1"]


def test_a_resuming_unit_starts_ahead_of_an_earlier_planned_new_unit() -> None:
    graph = [new("a/1"), resuming("b/1")]

    assert ready(graph, slots=1) == ["b/1"]


def test_a_rework_starts_ahead_of_a_resuming_unit() -> None:
    graph = [resuming("a/1"), rework("b/1", 7)]

    assert ready(graph, slots=1) == ["b/1"]


def test_with_two_slots_the_new_unit_is_the_one_left_waiting() -> None:
    graph = [new("a/1"), resuming("b/1"), rework("c/1", 7)]

    assert ready(graph, slots=2) == ["c/1", "b/1"]


def test_with_room_for_all_three_they_are_returned_in_class_order() -> None:
    graph = [new("a/1"), resuming("b/1"), rework("c/1", 7)]

    assert ready(graph, slots=3) == ["c/1", "b/1", "a/1"]


# --- 1.6 planned order within a kind, and nothing the other rules refuse -----------


def test_units_of_one_kind_start_in_the_order_they_were_planned() -> None:
    for make in (new, resuming):
        graph = [make("a/1"), make("b/1"), make("c/1")]
        assert ready(graph, slots=2) == ["a/1", "b/1"]

    graph = [rework("a/1", 1), rework("b/1", 2), rework("c/1", 3)]
    assert ready(graph, slots=2, ceiling=10) == ["a/1", "b/1"]


def test_a_resuming_unit_waits_at_the_ceiling_while_a_rework_starts() -> None:
    graph = [at_review("a/1", 1), resuming("b/1"), rework("c/1", 2)]

    assert ready(graph, ceiling=2) == ["c/1"]


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
