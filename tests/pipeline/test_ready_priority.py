"""Priority orders the ready units inside their class and nothing else."""

from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING, ready_units
from tests.factories import stored_unit


def new(uid: str, **kw):
    return stored_unit(uid, change=uid.split("/")[0], **kw)


def started(graph, *, slots: int = 1, **kw) -> list[str]:
    return [u.id for u in ready_units(graph, max_concurrent=slots, depth_cap=9, **kw)]


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


def test_an_open_pull_request_is_not_displaced_by_a_prerequisite_of_an_urgent_unit() -> None:
    graph = [
        new("review/1", state=IN_REVIEW, pr=3),
        new("base/1"),
        new("fix/1", priority=1, depends_on=("base/1",)),
    ]

    assert started(graph, slots=2, max_units_in_progress=9)[0] == "base/1"
