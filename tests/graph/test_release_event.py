"""A unit held by the hold label waits in `held`; the label coming off resumes
its thread with a `release` event and it waits for review again (docs/unit-graph.md,
Events become resume commands)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.graph.state import EventKind, Node, ResumeEvent
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.units import HELD, IN_REVIEW
from tests.factories import unit
from tests.graph_driver import FakeTracer, fresh, position, tick

HOLD = ResumeEvent(kind=EventKind.HOLD)
RELEASE = ResumeEvent(kind=EventKind.RELEASE)


def test_a_hold_event_records_that_a_reviewer_held_the_unit(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)

    tick(tmp_path, recorder, event=HOLD)

    stored = recorder.store.get(unit().id)
    assert stored.state == HELD
    assert stored.held_by == "reviewer"


def test_a_release_event_returns_the_thread_to_waiting_for_review(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    tick(tmp_path, recorder, event=HOLD)
    assert position(tmp_path).next == (Node.HELD,)
    built = len(recorder.events)
    tracer = FakeTracer()

    outcome = tick(tmp_path, recorder, event=RELEASE, tracer=tracer)

    assert outcome.status == RunStatus.OPEN
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)
    stored = recorder.store.get(unit().id)
    assert stored.state == IN_REVIEW
    assert stored.held_by == ""
    assert len(recorder.events) == built, "nothing ran"
    assert set(tracer.names) <= {"await_review", "held"}


def test_a_released_thread_takes_a_rework_again(tmp_path: Path) -> None:
    """What arrived during the hold is delivered by the next poll as it would
    be to any unit waiting for review."""
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    tick(tmp_path, recorder, event=HOLD)
    tick(tmp_path, recorder, event=RELEASE)

    tick(
        tmp_path,
        recorder,
        event=ResumeEvent(kind=EventKind.REWORK, reason="new comment", feedback="rename it"),
    )

    assert position(tmp_path).next == (Node.REWORK,)
    assert recorder.store.get(unit().id).feedback == "rename it"


def test_a_released_thread_can_be_held_again(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    tick(tmp_path, recorder, event=HOLD)
    tick(tmp_path, recorder, event=RELEASE)

    outcome = tick(tmp_path, recorder, event=HOLD)

    assert outcome.status == RunStatus.HELD
    assert position(tmp_path).next == (Node.HELD,)
    assert recorder.store.get(unit().id).held_by == "reviewer"
