"""Units that have never run start by the age of their stack, inside their priority."""

import pytest

from agent_build_kit.pipeline.units import CLOSED, HELD, IN_REVIEW, MERGED, PLANNED, SATISFIED
from tests.factories import new_unit as new
from tests.factories import started_ids as started


def test_a_prerequisite_of_an_old_unit_starts_before_a_newer_unrelated_unit() -> None:
    graph = [new("old/1", depends_on=("base/1",)), new("newer/1"), new("base/1")]

    assert started(graph) == ["base/1"]


def test_a_prerequisite_of_only_newer_units_does_not_take_an_older_units_place() -> None:
    graph = [new("older/1"), new("newer/1", depends_on=("base/1",)), new("base/1")]

    assert started(graph) == ["older/1"]


def test_a_chain_gives_its_oldest_age_to_the_ready_unit() -> None:
    graph = [
        new("oldest/1", depends_on=("mid/1",)),
        new("solo/1"),
        new("mid/1", depends_on=("base/1",)),
        new("base/1"),
    ]

    assert started(graph) == ["base/1"]


def test_depth_and_the_number_of_waiters_do_not_decide() -> None:
    graph = [
        new("old/1", depends_on=("one/1",)),
        new("n1/1", depends_on=("many/1",)),
        new("n2/1", depends_on=("n1/1",)),
        new("n3/1", depends_on=("n2/1",)),
        new("many/1"),
        new("one/1"),
    ]

    assert started(graph) == ["one/1"]


def test_a_tie_goes_to_the_units_own_planned_position() -> None:
    graph = [
        new("old/1", depends_on=("first/1", "second/1")),
        new("first/1"),
        new("second/1"),
    ]

    assert started(graph, slots=2) == ["first/1", "second/1"]


def test_a_unit_waiting_on_two_prerequisites_gives_its_age_to_both() -> None:
    graph = [
        new("old/1", depends_on=("a/1", "b/1")),
        new("solo/1"),
        new("a/1"),
        new("b/1"),
    ]

    assert started(graph, slots=2) == ["a/1", "b/1"]


def test_an_open_pull_request_still_starts_before_a_prerequisite_of_an_old_unit() -> None:
    review = new("review/1", state=PLANNED, pr=7, feedback="rework")
    graph = [new("old/1", depends_on=("base/1",)), new("base/1"), review]

    assert started(graph) == ["review/1"]


def test_a_resumed_build_still_starts_before_a_prerequisite_of_an_old_unit() -> None:
    paused = new("paused/1", branch="spec/paused/1")
    graph = [new("old/1", depends_on=("base/1",)), new("base/1"), paused]

    assert started(graph) == ["paused/1"]


def test_a_unit_that_gates_several_waiting_units_goes_ahead_of_standalone_ones() -> None:
    graph = [
        new("w1/1", depends_on=("gate/1",)),
        new("w2/1", depends_on=("gate/1",)),
        new("s1/1"),
        new("s2/1"),
        new("gate/1"),
    ]

    assert started(graph, slots=3) == ["gate/1", "s1/1", "s2/1"]


def test_age_decides_only_between_units_of_equal_effective_priority() -> None:
    graph = [
        new("old/1", depends_on=("base/1",)),
        new("solo/1"),
        new("fix/1", priority=1, depends_on=("urgent/1",)),
        new("urgent/1"),
        new("base/1"),
    ]

    assert started(graph, slots=3) == ["urgent/1", "base/1", "solo/1"]


def test_a_prerequisite_of_a_priority_1_unit_goes_ahead_of_an_older_unit_nothing_waits_on() -> None:
    graph = [
        new("old/1", priority=3),
        new("base/1", priority=3),
        new("fix/1", priority=1, depends_on=("base/1",)),
    ]

    assert started(graph) == ["base/1"]


def test_with_the_limit_reached_an_unblocker_does_not_start() -> None:
    graph = [
        new("review/1", state=IN_REVIEW, pr=3),
        new("old/1", depends_on=("base/1",)),
        new("base/1"),
    ]

    assert started(graph, slots=2, max_units_in_progress=1) == []


def test_with_one_place_free_an_unblocker_takes_it_before_a_newer_unit() -> None:
    graph = [
        new("review/1", state=IN_REVIEW, pr=3),
        new("old/1", depends_on=("base/1",)),
        new("newer/1"),
        new("base/1"),
    ]

    assert started(graph, slots=2, max_units_in_progress=2) == ["base/1"]


def test_with_one_place_free_an_unblocker_does_not_take_it_before_an_older_unit() -> None:
    graph = [
        new("review/1", state=IN_REVIEW, pr=3),
        new("older/1"),
        new("newer/1", depends_on=("base/1",)),
        new("base/1"),
    ]

    assert started(graph, slots=2, max_units_in_progress=2) == ["older/1"]


def test_no_place_held_by_a_waiting_unit_is_lent_to_its_prerequisite() -> None:
    graph = [
        new("review/1", state=IN_REVIEW, pr=3),
        new("old/1", depends_on=("base/1",), branch="spec/old/1"),
        new("base/1"),
    ]

    assert started(graph, slots=2, max_units_in_progress=2) == []


@pytest.mark.parametrize("finished", [MERGED, CLOSED])
def test_a_merged_or_closed_unit_gives_no_age(finished: str) -> None:
    graph = [new("gone/1", state=finished, depends_on=("base/1",)), new("solo/1"), new("base/1")]

    assert started(graph) == ["solo/1"]


def test_an_old_unit_waiting_through_a_satisfied_one_gives_its_age() -> None:
    graph = [
        new("old/1", depends_on=("sat/1",)),
        new("solo/1"),
        new("sat/1", state=SATISFIED, depends_on=("base/1",)),
        new("base/1"),
    ]

    assert started(graph) == ["base/1"]


def test_an_old_unit_in_another_repo_gives_its_age() -> None:
    graph = [
        new("old/1", repo="platform", depends_on=("base/1",)),
        new("solo/1"),
        new("base/1"),
    ]

    assert started(graph) == ["base/1"]


def test_a_cycle_among_the_waiters_does_not_loop() -> None:
    graph = [
        new("x/1", depends_on=("base/1", "y/1")),
        new("y/1", depends_on=("x/1",)),
        new("solo/1"),
        new("base/1"),
    ]

    assert started(graph) == ["base/1"]


@pytest.mark.parametrize("waiter_state", [HELD, PLANNED])
def test_a_unit_the_round_excluded_gives_no_age(waiter_state: str) -> None:
    graph = [
        new("old/1", state=waiter_state, depends_on=("base/1",)),
        new("newer/1"),
        new("base/1"),
    ]

    assert started(graph, excluded={"old/1"}) == ["newer/1"]


def test_an_excluded_prerequisite_is_not_started() -> None:
    graph = [new("old/1", depends_on=("base/1",)), new("base/1", state=HELD)]

    assert started(graph, excluded={"base/1"}) == []
