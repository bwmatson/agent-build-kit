"""A unit in review or held waits in an interrupt of its thread, and the poller's
events and `abk requeue` resume it as commands (docs/unit-graph.md, Events become
resume commands). A delivery runs only the wait's own work and leaves the thread
at the node the event routes to; the tick runs that node."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import EventKind, Node, ResumeEvent
from agent_build_kit.graph.unit import resume_unit
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING, branch_name
from agent_build_kit.pipeline.workspaces import BranchBusy, branch_lock
from tests.factories import unit
from tests.graph_driver import FakeTracer, fresh, position, tick
from tests.runner_fakes import Killed, make_runner

# The only spans a delivery makes: the wait node acting on the event.
WAIT_SPANS = {"await_review", "held"}


def test_an_event_for_a_thread_mid_node_is_refused_while_another_holds_the_branch(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, kill_after="commit:feat")
    with pytest.raises(Killed):
        tick(tmp_path, recorder)
    assert position(tmp_path).next == (Node.IMPLEMENT,)
    ran = list(recorder.events)

    with branch_lock(branch_name(unit()), root=tmp_path / "locks"), pytest.raises(BranchBusy):
        tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.REWORK))

    assert recorder.events == ran, "the node was not run again"
    assert position(tmp_path).next == (Node.IMPLEMENT,)


def test_an_event_for_a_thread_killed_mid_node_is_refused_and_runs_nothing(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, kill_after="commit:feat")
    with pytest.raises(Killed):
        tick(tmp_path, recorder)
    ran = list(recorder.events)

    with pytest.raises(BranchBusy):
        tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.REWORK, reason="comment"))

    assert recorder.events == ran, "nothing ran"
    left = position(tmp_path)
    assert left.next == (Node.IMPLEMENT,), "the thread is where the kill left it"
    assert left.state is not None
    assert left.state.event is None, "the event was not recorded"


def test_an_event_during_a_node_is_refused_and_delivered_once_the_run_has_returned(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    event = ResumeEvent(
        kind=EventKind.REWORK, reason="conflict", feedback="the branch conflicts with main"
    )
    during: list[Any] = []

    def review_while_the_event_arrives(**kwargs: Any) -> str:
        # On the worker thread the review node runs on, under the run's lock.
        with pytest.raises(BranchBusy):
            tick(tmp_path, recorder, event=event)
        during.append(position(tmp_path))
        return recorder.review(**kwargs)

    tick(tmp_path, recorder, run_review=review_while_the_event_arrives)

    (mid_node,) = during
    assert mid_node.next == (Node.REVIEW,), "the thread was left as the running node had it"
    assert mid_node.state is not None
    assert mid_node.state.event is None
    assert "claude:rework" not in recorder.events
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)
    built = len(recorder.prompts)

    tick(tmp_path, recorder, event=event)

    assert position(tmp_path).next == (Node.REWORK,), "acted on, and routed"
    assert len(recorder.prompts) == built, "no agent ran in the delivery"
    tick(tmp_path, recorder)
    assert "the branch conflicts with main" in recorder.prompts[-1]
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_an_event_for_a_unit_waiting_in_review_is_delivered_at_once(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    runner = make_runner(recorder.store, recorder, tmp_path)

    async def deliver() -> RunOutcome:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            return await asyncio.wait_for(
                resume_unit(
                    runner,
                    unit(),
                    base="main",
                    graph=[],
                    saver=saver,
                    event=ResumeEvent(kind=EventKind.HOLD),
                    locks=tmp_path / "locks",
                ),
                timeout=10,
            )

    assert asyncio.run(deliver()).status == RunStatus.HELD


@pytest.mark.parametrize(
    ("reason", "feedback"),
    [
        ("comment", "Use a Sequence, list is invariant"),
        ("changes requested", "Rename the registry"),
        ("label", "agent-rework"),
        ("failing check", "tier 1 failed: E   ImportError"),
        ("conflict", "the branch conflicts with main in src/app.py"),
    ],
)
def test_a_rework_event_leaves_the_thread_at_rework_and_the_next_tick_runs_it(
    tmp_path: Path, reason: str, feedback: str
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    built = len(recorder.prompts)
    tracer = FakeTracer()

    delivered = tick(
        tmp_path,
        recorder,
        event=ResumeEvent(kind=EventKind.REWORK, reason=reason, feedback=feedback),
        tracer=tracer,
    )

    assert len(recorder.prompts) == built, "the delivery ran no agent"
    assert set(tracer.names) <= WAIT_SPANS, "and no node but the wait"
    assert delivered.status == RunStatus.OPEN
    assert position(tmp_path).next == (Node.REWORK,)
    assert recorder.store.get(unit().id).state == RUNNING

    tracer = FakeTracer()
    outcome = tick(tmp_path, recorder, tracer=tracer)

    assert "rework" in tracer.names
    assert tracer.names.index("rework") < tracer.names.index("checks")
    assert "tests" not in tracer.names
    assert "implement" not in tracer.names
    assert len(recorder.prompts) == built + 1, "one rework, nothing rebuilt"
    assert feedback in recorder.prompts[-1]
    assert outcome.status == RunStatus.OPEN
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_moved_base_leaves_the_thread_at_prepare_and_the_next_tick_runs_it(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    built = len(recorder.prompts)
    tracer = FakeTracer()

    tick(
        tmp_path,
        recorder,
        event=ResumeEvent(kind=EventKind.BASE_MOVED, reason="main"),
        tracer=tracer,
    )

    assert set(tracer.names) <= WAIT_SPANS
    assert position(tmp_path).next == (Node.PREPARE,)
    assert recorder.store.get(unit().id).state == RUNNING

    tracer = FakeTracer()
    outcome = tick(tmp_path, recorder, tracer=tracer)

    assert "prepare" in tracer.names
    assert "tests" not in tracer.names
    assert len(recorder.prompts) == built, "the work was not redone"
    assert outcome.status == RunStatus.OPEN


def test_a_hold_event_resumes_the_thread_into_held_and_it_waits_there(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    tracer = FakeTracer()

    outcome = tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.HOLD), tracer=tracer)

    assert outcome.status == RunStatus.HELD
    assert position(tmp_path).next == (Node.HELD,), "held waits in an interrupt"


@pytest.mark.parametrize("kind", [EventKind.MERGED, EventKind.CLOSED])
def test_a_merge_or_a_close_ends_the_thread_and_deletes_it(tmp_path: Path, kind: EventKind) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)

    tick(tmp_path, recorder, event=ResumeEvent(kind=kind))

    gone = position(tmp_path)
    assert gone.state is None
    assert gone.next == ()


@pytest.mark.parametrize("mode", ["resume", "restart", "rework"])
def test_a_requeue_leaves_a_held_thread_at_prepare_and_runs_nothing(
    tmp_path: Path, mode: str
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    assert tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.HOLD)).status == RunStatus.HELD
    assert position(tmp_path).next == (Node.HELD,)
    built = len(recorder.events)
    tracer = FakeTracer()

    tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.REQUEUE, reason=mode), tracer=tracer)

    assert set(tracer.names) <= WAIT_SPANS
    assert len(recorder.events) == built, "nothing ran"
    assert position(tmp_path).next == (Node.PREPARE,)
    assert recorder.store.get(unit().id).state == RUNNING

    tracer = FakeTracer()
    outcome = tick(tmp_path, recorder, tracer=tracer)

    assert "prepare" in tracer.names
    assert outcome.status == RunStatus.OPEN
    assert outcome.pr == 7


def test_a_requeue_leaves_a_failed_thread_at_prepare_and_runs_nothing(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, tier1_ok=False)
    assert tick(tmp_path, recorder).status == RunStatus.FAILED
    recorder.tier1_ok = True
    built = len(recorder.events)
    tracer = FakeTracer()

    tick(
        tmp_path,
        recorder,
        event=ResumeEvent(kind=EventKind.REQUEUE, reason="resume"),
        tracer=tracer,
    )

    assert tracer.names == [], "a failed thread has no wait to run"
    assert len(recorder.events) == built
    assert position(tmp_path).next == (Node.PREPARE,)

    outcome = tick(tmp_path, recorder, tracer=tracer)

    assert "prepare" in tracer.names
    assert outcome.status == RunStatus.OPEN


def test_a_persons_words_in_a_rework_event_stay_a_persons_words(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)

    tick(
        tmp_path,
        recorder,
        event=ResumeEvent(
            kind=EventKind.REWORK, reason="new comment", feedback="rename it", from_person=True
        ),
    )

    stored = recorder.store.get(unit().id)
    assert stored.feedback == "rename it"
    assert stored.feedback_from_person


def test_a_build_held_before_a_step_waits_in_held_and_a_requeue_runs_it_again(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    held = tick(
        tmp_path,
        recorder,
        upstream_incomplete=lambda u: (Cause.UPSTREAM_WENT_BACK, "upstream reworking"),
    )

    assert held.status == RunStatus.HELD
    assert position(tmp_path).next == (Node.HELD,)
    assert recorder.store.get(unit().id).state == "planned", "recorded once, as the hold left it"

    tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.REQUEUE, reason="resume"))
    outcome = tick(tmp_path, recorder)

    assert outcome.status == RunStatus.OPEN
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_parking_a_unit_in_review_keeps_what_it_had_and_leaves_the_thread_waiting(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    before = recorder.store.get(unit().id)
    assert before.state == IN_REVIEW
    assert before.approved
    built = len(recorder.prompts)
    tracer = FakeTracer()

    tick(
        tmp_path,
        recorder,
        event=ResumeEvent(kind=EventKind.UPSTREAM_CHANGED, reason="feature/0 is rebasing"),
        tracer=tracer,
    )

    parked = recorder.store.get(unit().id)
    assert parked.state == PLANNED
    assert parked.cause is Cause.UPSTREAM_WENT_BACK
    assert "feature/0 is rebasing" in parked.note
    assert (parked.approved, parked.branch, parked.pr) == (
        before.approved,
        before.branch,
        before.pr,
    )
    assert set(tracer.names) <= WAIT_SPANS
    assert len(recorder.prompts) == built, "the delivery ran no agent"
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,), "the thread still waits for review"


@pytest.mark.parametrize("kind", [k for k in EventKind if k is not EventKind.UPSTREAM_CHANGED])
def test_no_other_event_kind_sets_a_unit_in_review_to_planned(
    tmp_path: Path, kind: EventKind
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)

    tick(tmp_path, recorder, event=ResumeEvent(kind=kind, reason="x", feedback="x"))

    assert recorder.store.get(unit().id).state != PLANNED
