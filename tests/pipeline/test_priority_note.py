"""`priority_note` says a unit's effective priority and where it comes from.

The graph label, the ready queue and the tick's priority line all print it.
"""

from agent_build_kit.pipeline.diagram import render_mermaid
from agent_build_kit.pipeline.units import RUNNING, priority_note
from tests.factories import stored_unit as unit


def node(diagram: str, unit_id: str) -> str:
    return next(line for line in diagram.splitlines() if line.strip().startswith(f"{unit_id}["))


def test_an_unpromoted_unit_is_noted_with_its_own_priority_and_a_normal_one_with_nothing() -> None:
    urgent, plain = unit("a", priority=1), unit("b")

    assert priority_note(urgent, [urgent, plain]) == "priority 1"
    assert priority_note(plain, [urgent, plain]) == ""


def test_a_promoted_unit_names_the_unit_it_was_promoted_from() -> None:
    base = unit("base", priority=1, promoted_from="app/9")
    waiter = unit("app/9", priority=1, depends_on=("base",))

    assert priority_note(base, [base, waiter]) == "priority 1, promoted from app/9"


def test_a_started_unit_a_more_urgent_waiter_covers_names_the_waiter() -> None:
    base = unit("base", priority=3, state=RUNNING, branch="spec/base")
    waiter = unit("app/9", priority=1, depends_on=("base",))

    assert priority_note(base, [base, waiter]) == "priority 1, from app/9"


def test_a_promoted_unit_a_more_urgent_waiter_now_covers_names_that_waiter() -> None:
    base = unit("base", priority=1, state=RUNNING, branch="spec/base", promoted_from="app/9")
    waiters = [
        unit("app/9", priority=1, depends_on=("base",)),
        unit("app/12", priority=0, depends_on=("base",)),
    ]

    assert priority_note(base, [base, *waiters]) == "priority 0, from app/12"


def test_a_waiter_that_is_not_more_urgent_adds_no_source() -> None:
    base = unit("base", priority=2)
    waiter = unit("app/9", priority=4, depends_on=("base",))

    assert priority_note(base, [base, waiter]) == "priority 2"


def test_the_diagram_label_carries_the_note_and_a_normal_unit_carries_none() -> None:
    promoted = unit("base", priority=1, promoted_from="app/9")
    covered = unit("run", priority=3, state=RUNNING, branch="spec/run")
    waiters = [
        unit("app/9", priority=1, depends_on=("base", "run")),
        unit("plain"),
    ]

    diagram = render_mermaid([promoted, covered, *waiters])

    assert "priority 1, promoted from app/9" in node(diagram, "base")
    assert "priority 1, from app/9" in node(diagram, "run")
    assert "priority" not in node(diagram, "plain")
