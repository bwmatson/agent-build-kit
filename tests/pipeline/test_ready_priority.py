"""Priority orders the ready units inside their class and nothing else."""

from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING
from tests.factories import new_unit as new
from tests.factories import started_ids as started


def test_priority_does_not_move_a_new_unit_ahead_of_an_open_pull_request() -> None:
    review = new("review/1", state=PLANNED, pr=7, feedback="rework", priority=5)

    assert started([new("urgent/1", priority=1), review]) == ["review/1"]


def test_priority_does_not_move_a_new_unit_ahead_of_a_resumed_build() -> None:
    paused = new("paused/1", branch="spec/paused/1", priority=5)

    assert started([new("urgent/1", priority=1), paused]) == ["paused/1"]


def test_a_more_urgent_unit_planned_later_starts_first() -> None:
    assert started([new("early/1"), new("late/1", priority=1)]) == ["late/1"]


def test_equal_priorities_fall_to_the_planned_order() -> None:
    assert started([new("early/1", priority=2), new("late/1", priority=2)]) == ["early/1"]


def test_a_more_urgent_unit_that_is_not_ready_does_not_stop_a_ready_one() -> None:
    graph = [
        new("base/1", repo="platform", state=RUNNING),
        new("blocked/1", priority=1, depends_on=("base/1",)),
        new("ready/1", priority=5),
    ]

    assert started(graph, slots=2) == ["ready/1"]


def test_a_prerequisite_takes_the_priority_of_a_unit_waiting_on_it() -> None:
    graph = [
        new("older/1"),
        new("base/1"),
        new("fix/1", priority=1, depends_on=("base/1",)),
    ]

    assert started(graph) == ["base/1"]


def test_a_unit_left_out_of_the_round_gives_its_prerequisite_no_priority() -> None:
    graph = [
        new("older/1"),
        new("base/1"),
        new("fix/1", priority=1, depends_on=("base/1",)),
    ]

    assert started(graph, excluded={"fix/1"}) == ["older/1"]


def test_a_unit_in_review_does_not_stop_an_urgent_prerequisite_starting() -> None:
    graph = [
        new("review/1", state=IN_REVIEW, pr=3),
        new("base/1"),
        new("fix/1", priority=1, depends_on=("base/1",)),
    ]

    assert started(graph, slots=2, max_units_in_progress=9)[0] == "base/1"
