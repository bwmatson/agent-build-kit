"""A unit held by the hold label waits in `held`; the label coming off resumes
its thread with a `release` event and it waits for review again (docs/unit-graph.md,
Events become resume commands)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit import config as config_module
from agent_build_kit.graph.state import EventKind, Node, ResumeEvent
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import HeldBy
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, RUNNING
from tests.factories import unit
from tests.graph_driver import FakeTracer, fresh, position, tick
from tests.runner_fakes import Recorder


def limited(**limits: int | None) -> None:
    """The given limits; the suite's autouse fixture puts the config back."""
    current = config_module.active()
    config_module.activate(
        current.model_copy(update={"limits": current.limits.model_copy(update=limits)}),
        config_module.active_root(),
    )


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


DEPTH_NOTE = events.DEPTH_HOLD.format(new_base="main", depth=3, cap=2) + (
    events.DEPTH_HOLD_BASE.format(old_base="spec/c/1")
)


def depth_held(tmp_path: Path) -> Recorder:
    """Held for depth while the thread still waits for review, then taken over by the label."""
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    recorder.store.set_state(
        unit().id, HELD, note=DEPTH_NOTE, held_by=HeldBy.DEPTH, held_base="spec/c/1"
    )
    tick(tmp_path, recorder, event=HOLD)
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.held_by) == (HELD, "reviewer")
    return recorder


def test_a_depth_hold_the_label_took_over_is_held_for_depth_again_while_beyond_the_cap(
    tmp_path: Path,
) -> None:
    """A merge cannot free it with the label on, and the label coming off gives
    it back to the depth hold, with the branch it is still on, for a later merge."""
    recorder = depth_held(tmp_path)
    limited(stack_depth_rebase_cap=0)

    outcome = tick(tmp_path, recorder, event=RELEASE)

    assert outcome.status == RunStatus.HELD
    assert position(tmp_path).next == (Node.HELD,)
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.held_by) == (HELD, "depth")
    assert stored.held_base == "spec/c/1"
    assert events.held_for_depth(stored)


def test_a_depth_hold_the_label_took_over_is_moved_when_a_merge_brought_it_within_the_cap(
    tmp_path: Path,
) -> None:
    recorder = depth_held(tmp_path)

    tick(tmp_path, recorder, event=RELEASE)

    assert position(tmp_path).next == (Node.PREPARE,), "the run takes up where it restacks"
    assert recorder.store.get(unit().id).state == RUNNING


def test_a_hold_the_label_did_not_make_stays_when_the_label_comes_and_goes(
    tmp_path: Path,
) -> None:
    """Held by the review loop while the thread still waits for review: the label
    added and removed neither takes the hold over nor releases it."""
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    recorder.store.set_state(unit().id, HELD, note="rounds spent", held_by=HeldBy.REVIEW)
    before = recorder.store.history(unit().id)

    tick(tmp_path, recorder, event=HOLD)
    tick(tmp_path, recorder, event=RELEASE)

    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.held_by) == (HELD, "review")
    assert recorder.store.history(unit().id) == before
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)
