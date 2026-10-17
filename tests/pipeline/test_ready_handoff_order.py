"""A handoff unit breaks a tie of equal priority; it never goes ahead of a more urgent unit.

Among units that have never run the order is effective priority, then handoff
units before the others of equal priority, then effective age, then planned
position. Open pull requests and paused builds still come first, and the room
accounting is the one `test_blocked_units.py` pins.
"""

from tests.factories import new_unit as new
from tests.factories import started_ids


def worked(uid: str, **kw):
    """A planned unit a run began and stopped: it has recorded its branch."""
    return new(uid, branch=f"spec/{uid}", **kw)


def chosen(graph, *, limit: int = 9, slots: int = 9) -> list[str]:
    return started_ids(graph, slots=slots, max_units_in_progress=limit)


def test_a_more_urgent_new_unit_is_offered_before_a_handoff_prerequisite() -> None:
    graph = [
        worked("blocked/1", depends_on=("prerequisite/1",)),
        new("prerequisite/1", priority=2),
        new("first/1", priority=1),
        new("second/1", priority=1),
    ]

    assert chosen(graph) == ["first/1", "second/1", "prerequisite/1"]


def test_handoff_units_go_first_among_equal_priorities_then_by_age() -> None:
    graph = [
        new("other/1"),
        new("older/1"),
        new("newer/1"),
        worked("blocks-older/1", depends_on=("older/1",)),
        worked("blocks-newer/1", depends_on=("newer/1",)),
        new("urgent/1", priority=2),
    ]

    assert chosen(graph) == ["urgent/1", "older/1", "newer/1", "other/1"]


def test_a_paused_build_still_precedes_a_more_urgent_new_unit_handoff_or_not() -> None:
    graph = [
        worked("paused/1"),
        worked("blocked/1", depends_on=("handed/1",)),
        new("other/1", priority=1),
        new("handed/1", priority=1),
    ]

    assert chosen(graph) == ["paused/1", "handed/1", "other/1"]


def test_a_more_urgent_unit_takes_the_freed_place_before_a_less_urgent_handoff_unit() -> None:
    graph = [
        new("busy/1", state="in_review", pr=1),
        worked("blocked/1", depends_on=("handed/1",)),
        new("handed/1"),
        new("urgent/1", priority=1),
    ]

    assert chosen(graph, limit=2) == ["urgent/1"]
    assert chosen(graph, limit=3) == ["urgent/1", "handed/1"]


def test_a_more_urgent_unit_of_a_full_project_is_skipped_for_a_handoff_of_one_with_room() -> None:
    graph = [
        new("full/1", state="in_review", pr=1, project="api"),
        new("urgent/1", priority=1, project="api"),
        worked("blocked/1", project="web", depends_on=("handed/1",)),
        new("handed/1", project="web"),
        new("free/1", priority=2, project="docs"),
    ]

    assert chosen(graph, limit=1) == ["free/1", "handed/1"]
