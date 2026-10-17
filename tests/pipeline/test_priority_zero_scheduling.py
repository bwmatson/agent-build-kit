"""Priority 0 starts first and bypasses no limit.

The emergency lane changes the sort position and nothing else: it neither
raises a limit nor stops a running unit.
"""

from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
    effective_priority,
)
from tests.factories import new_unit as new
from tests.factories import started_ids
from tests.factories import worked_unit as worked


def test_a_later_planned_priority_zero_unit_starts_before_an_earlier_priority_one() -> None:
    assert started_ids([new("early/1", priority=1), new("late/1", priority=0)]) == ["late/1"]


def test_a_prerequisite_of_a_priority_zero_unit_has_effective_priority_zero() -> None:
    graph = [
        new("base/1"),
        new("middle/1", depends_on=("base/1",)),
        new("top/1", priority=0, depends_on=("middle/1",)),
    ]

    assert effective_priority(graph[1], graph) == 0
    assert effective_priority(graph[0], graph) == 0


def test_a_prerequisite_of_a_priority_zero_unit_starts_before_an_older_priority_one() -> None:
    graph = [
        new("older/1", priority=1),
        new("base/1"),
        new("top/1", priority=0, depends_on=("base/1",)),
    ]

    assert started_ids(graph) == ["base/1"]


def test_an_open_pull_request_still_starts_before_a_never_run_priority_zero_unit() -> None:
    review = new("review/1", state=PLANNED, pr=7, feedback="rework", priority=5)

    assert started_ids([new("zero/1", priority=0), review]) == ["review/1"]


def test_a_satisfied_or_excluded_waiter_of_priority_zero_lends_nothing() -> None:
    base = new("base/1")

    assert effective_priority(base, [base, new("top/1", priority=0, depends_on=("base/1",))]) == 0
    finished = new("top/1", priority=0, depends_on=("base/1",), state=SATISFIED)
    merged = new("top/1", priority=0, depends_on=("base/1",), state=MERGED)
    assert effective_priority(base, [base, finished]) == 3
    assert effective_priority(base, [base, merged]) == 3
    waiting = new("top/1", priority=0, depends_on=("base/1",))
    assert effective_priority(base, [base, waiting], {"top/1"}) == 3


def test_a_priority_zero_unit_waits_when_the_limit_on_units_in_progress_is_reached() -> None:
    graph = [new("busy/1", state=IN_REVIEW, pr=1), new("zero/1", priority=0)]

    assert started_ids(graph, max_units_in_progress=1) == []

    freed = [new("busy/1", state=MERGED, pr=1), *graph[1:]]
    assert started_ids(freed, max_units_in_progress=1) == ["zero/1"]


def test_a_priority_zero_unit_starts_first_when_a_place_frees() -> None:
    graph = [new("other/1", priority=1), new("zero/1", priority=0)]

    assert started_ids(graph, max_units_in_progress=1) == ["zero/1"]


def test_a_priority_zero_unit_waits_when_the_cap_on_units_running_is_reached() -> None:
    graph = [new("run/1", state=RUNNING), new("zero/1", priority=0)]

    assert started_ids(graph, slots=1) == []
    assert started_ids(graph, slots=2) == ["zero/1"]


def test_a_priority_zero_unit_waits_when_its_project_is_full() -> None:
    graph = [
        new("full/1", state=IN_REVIEW, pr=1, project="api"),
        new("zero/1", priority=0, project="api"),
        new("other/1", priority=1, project="web"),
    ]

    assert started_ids(graph, max_units_in_progress=1) == ["other/1"]


def test_a_running_unit_is_not_stopped_by_a_priority_zero_unit_becoming_ready() -> None:
    graph = [new("run/1", state=RUNNING, priority=5), new("zero/1", priority=0)]

    assert started_ids(graph, slots=2) == ["zero/1"]
    assert started_ids(graph, slots=1) == []


def test_a_freed_place_goes_to_the_prerequisite_of_a_priority_zero_unit_first() -> None:
    graph = [
        new("busy/1", state=IN_REVIEW, pr=1),
        worked("blocked-one/1", depends_on=("one/1",)),
        worked("blocked-zero/1", depends_on=("zero/1",), priority=0),
        new("one/1", priority=1),
        new("zero/1"),
    ]

    assert started_ids(graph, slots=9, max_units_in_progress=2) == ["zero/1"]
