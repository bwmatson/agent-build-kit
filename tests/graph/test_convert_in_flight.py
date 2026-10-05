"""A store left by the classic engine converts to threads positioned at the
nodes the design names, and each unit then proceeds as it would have
(docs/unit-graph.md, Moving the units in flight)."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.convert import convert_units_in_flight
from agent_build_kit.graph.state import EventKind, Node, ResumeEvent
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED, branch_name
from tests.factories import unit
from tests.graph_driver import position, tick
from tests.runner_fakes import Recorder

UNIT = "add-marker/1"
WAITING = "rename the marker"


def stored(
    tmp_path: Path,
    *,
    state: str = PLANNED,
    resume_from: str = "",
    feedback: str = "",
    pr: int | None = None,
) -> Recorder:
    """A store as the classic engine left it, with a commit on the branch."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    store.set_state(UNIT, state, pr=pr, branch=branch_name(unit()), resume_from=resume_from)
    if feedback:
        store.set_feedback(UNIT, feedback, from_person=True)
    recorder = Recorder(store)
    recorder.made = 2
    return recorder


def convert(tmp_path: Path, store: UnitStore) -> tuple[str, ...]:
    async def go() -> tuple[str, ...]:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            return await convert_units_in_flight(saver, store)

    return asyncio.run(go())


@pytest.mark.parametrize(
    ("step", "node"),
    [
        ("tests", Node.TESTS),
        ("review", Node.REVIEW),
        ("rework_review", Node.REVIEW),
        ("verify", Node.VERIFY_BASE),
        ("restack", Node.PREPARE),
    ],
)
def test_a_unit_stopped_before_a_step_gets_a_thread_at_the_node_that_step_names(
    tmp_path: Path, step: str, node: Node
) -> None:
    recorder = stored(tmp_path, resume_from=step)

    assert convert(tmp_path, recorder.store) == (UNIT,)

    where = position(tmp_path)
    assert where.next == (node,)
    assert where.state is not None
    assert where.state.unit_id == UNIT


def test_a_unit_with_waiting_feedback_gets_a_thread_at_rework(tmp_path: Path) -> None:
    recorder = stored(tmp_path, feedback=WAITING)

    assert convert(tmp_path, recorder.store) == (UNIT,)

    assert position(tmp_path).next == (Node.REWORK,)


def test_a_unit_in_review_gets_a_thread_already_waiting_in_await_review(tmp_path: Path) -> None:
    recorder = stored(tmp_path, state=IN_REVIEW, pr=7)

    assert convert(tmp_path, recorder.store) == (UNIT,)

    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_held_unit_gets_a_thread_already_waiting_in_held(tmp_path: Path) -> None:
    recorder = stored(tmp_path, state=HELD)

    assert convert(tmp_path, recorder.store) == (UNIT,)

    assert position(tmp_path).next == (Node.HELD,)


def test_a_unit_with_nothing_in_flight_gets_no_thread(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])

    assert convert(tmp_path, store) == ()

    assert position(tmp_path).state is None


def test_converting_twice_leaves_the_threads_where_they_are(tmp_path: Path) -> None:
    recorder = stored(tmp_path, resume_from="review")
    convert(tmp_path, recorder.store)
    tick(tmp_path, recorder)
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)

    assert convert(tmp_path, recorder.store) == ()

    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_unit_converted_at_review_is_reviewed_and_goes_on_without_building(
    tmp_path: Path,
) -> None:
    recorder = stored(tmp_path, resume_from="review")
    convert(tmp_path, recorder.store)

    outcome = tick(tmp_path, recorder)

    assert outcome.status == RunStatus.OPEN
    assert recorder.events.count("review") == 1
    assert "claude:impl" not in recorder.events
    assert "claude:tests" not in recorder.events
    assert recorder.pr_opens == 1
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_unit_converted_at_verify_skips_review_and_pushes(tmp_path: Path) -> None:
    recorder = stored(tmp_path, resume_from="verify")
    recorder.store.record_approval(UNIT, recorder.head(tmp_path))
    convert(tmp_path, recorder.store)

    tick(tmp_path, recorder)

    assert "review" not in recorder.events
    assert recorder.events.count("push") == 1
    assert recorder.pr_opens == 1
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_unit_converted_with_waiting_feedback_reworks_it_once(tmp_path: Path) -> None:
    recorder = stored(tmp_path, feedback=WAITING)
    convert(tmp_path, recorder.store)

    tick(tmp_path, recorder)

    assert recorder.events.count("claude:rework") == 1
    assert WAITING in recorder.prompts[-1]
    assert "claude:impl" not in recorder.events
    assert recorder.store.get(UNIT).feedback == "", "acted on once"
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_comment_on_a_converted_unit_in_review_resumes_it_into_rework(tmp_path: Path) -> None:
    recorder = stored(tmp_path, state=IN_REVIEW, pr=7)
    convert(tmp_path, recorder.store)

    tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.REWORK, feedback=WAITING))
    assert position(tmp_path).next == (Node.REWORK,)
    tick(tmp_path, recorder)

    assert WAITING in recorder.prompts[-1]
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_converted_held_unit_is_requeued_into_prepare(tmp_path: Path) -> None:
    recorder = stored(tmp_path, state=HELD)
    convert(tmp_path, recorder.store)

    tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.REQUEUE))

    assert position(tmp_path).next == (Node.PREPARE,)


def test_a_merge_for_a_converted_unit_in_review_ends_its_thread(tmp_path: Path) -> None:
    recorder = stored(tmp_path, state=IN_REVIEW, pr=7)
    convert(tmp_path, recorder.store)

    tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.MERGED))

    assert position(tmp_path).state is None
