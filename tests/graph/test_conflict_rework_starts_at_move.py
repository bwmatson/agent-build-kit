"""A conflict rework delivered to a parked thread starts at the move, not at the rework (spec:
restack-conflicts, a conflict rework starts with the move).

`restack_onto` is faked at its edge, as `test_restack_step_in_prepare` does: it answers a clean
move, a conflict the resolver settled, or one it could not. What is asserted is where the event
leaves the thread, what is left of the conflict's feedback, and which agent steps ran.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.graph.state import EventKind, Node, ResumeEvent
from agent_build_kit.pipeline.stack_runner import Restacked
from agent_build_kit.pipeline.unit_store import FeedbackSource, ReworkKind
from tests.factories import unit
from tests.graph.test_build_path import once, restacked
from tests.graph_driver import FakeTracer, fresh, position, tick
from tests.runner_fakes import Recorder

CONFLICT = "The pull request conflicts with main in a.py"
ORDER = "ORDER: hunks first, then dependent files, then a port. Conflicted: a.py"
EVENT = ResumeEvent(
    kind=EventKind.REWORK,
    reason="merge conflict with its base",
    feedback=CONFLICT,
    feedback_source=FeedbackSource.CONFLICT,
    rework=ReworkKind.CONFLICT,
)


def parked(tmp_path: Path) -> Recorder:
    """A unit built to its review, its thread waiting there."""
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)
    return recorder


def run(tmp_path: Path, recorder: Recorder, **edges: Any) -> list[str]:
    """Deliver the conflict, then run the thread; the nodes that ran after the delivery."""
    tick(tmp_path, recorder, event=EVENT)
    tracer = FakeTracer()
    tick(tmp_path, recorder, tracer=tracer, **edges)
    return tracer.names


def porting() -> dict[str, Any]:
    """The edges the port reaches, which carry nothing over."""
    return dict(
        reset_to=lambda tree, onto, keep: None,
        tests_in=lambda tree: set(),
        tests_changed=lambda tree, ref: set(),
    )


def test_the_event_leaves_a_parked_thread_at_the_move_with_the_feedback_sourced_as_the_conflict(
    tmp_path: Path,
) -> None:
    recorder = parked(tmp_path)

    tick(tmp_path, recorder, event=EVENT)

    assert position(tmp_path).next == (Node.PREPARE,), "the move first, not the rework"
    stored = recorder.store.get(unit().id)
    assert stored.feedback == CONFLICT
    assert stored.feedback_source is FeedbackSource.CONFLICT


def test_a_clean_move_clears_the_conflict_and_the_thread_goes_to_checks_with_no_rework(
    tmp_path: Path,
) -> None:
    recorder = parked(tmp_path)

    names = run(tmp_path, recorder, restack_onto=once(restacked()))

    assert "rework" not in names and "adapt" not in names
    assert Node.CHECKS.value in names or Node.VERIFY_BASE.value in names
    assert recorder.store.get(unit().id).feedback == "", "the conflict is gone, so is its feedback"
    assert not any(CONFLICT in prompt for prompt in recorder.prompts)
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_move_the_resolver_settles_clears_the_conflict_and_calls_no_rework_agent(
    tmp_path: Path,
) -> None:
    recorder = parked(tmp_path)

    moves = once(restacked(resolved=("a.py",)))

    def settling(**kw: Any) -> Restacked | None:
        moved = moves(**kw)
        if moved is not None:
            kw["resolver"](ORDER, cwd=kw["tree"])
        return moved

    names = run(tmp_path, recorder, restack_onto=settling)

    assert "rework" not in names and "adapt" not in names
    assert recorder.store.get(unit().id).feedback == ""
    assert not any(CONFLICT in prompt for prompt in recorder.prompts)


def test_a_move_the_resolver_cannot_settle_runs_the_port_then_the_rework_on_the_conflict(
    tmp_path: Path,
) -> None:
    recorder = parked(tmp_path)

    names = run(
        tmp_path,
        recorder,
        restack_onto=once(restacked(conflict="CONFLICT in a.py")),
        **porting(),
    )

    assert names.index("adapt") < names.index("rework"), "the port first, then the rework"
    assert any(CONFLICT in prompt for prompt in recorder.prompts), "the rework is told the conflict"
