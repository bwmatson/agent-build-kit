"""A usage refusal before an agent step interrupts the thread with the guard's
resume time, and a later tick on which the guard allows resumes it there
(docs/unit-graph.md, Usage pauses)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.stack_runner import PauseInfo, RunStatus
from tests.graph_driver import fresh, position, tick

UNTIL = datetime(2030, 1, 1, 9, 30, tzinfo=UTC)
WINDOW = "session usage at 88%"


def test_a_refusal_before_an_agent_step_interrupts_with_the_reason_and_resume_time(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)

    outcome = tick(tmp_path, recorder, may_start=lambda: (False, WINDOW), resume_at=lambda: UNTIL)

    assert outcome.status == RunStatus.PAUSED
    assert WINDOW in outcome.detail
    paused = position(tmp_path)
    assert paused.next == (Node.TESTS,), "before the first agent step, not after it"
    assert paused.pause == PauseInfo(reason=WINDOW, until=UNTIL)
    assert not [e for e in recorder.events if e.startswith("claude")], "no agent ran"
    stored = recorder.store.get("add-marker/1")
    assert stored.state == "running", "interrupted, not put back to planned"


def test_a_tick_on_which_the_guard_allows_resumes_the_thread_where_it_stopped(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder, may_start=lambda: (False, WINDOW), resume_at=lambda: UNTIL)

    outcome = tick(tmp_path, recorder, may_start=lambda: (True, "usage fine"))

    assert outcome.status == RunStatus.OPEN
    assert recorder.events.count("claude:tests") == 1
    assert recorder.events.count("claude:impl") == 1
    assert position(tmp_path).pause is None


def test_a_tick_on_which_the_guard_still_refuses_leaves_the_thread_interrupted(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder, may_start=lambda: (False, WINDOW), resume_at=lambda: UNTIL)
    later = UNTIL + timedelta(hours=1)

    outcome = tick(
        tmp_path, recorder, may_start=lambda: (False, "weekly at 92%"), resume_at=lambda: later
    )

    assert outcome.status == RunStatus.PAUSED
    paused = position(tmp_path)
    assert paused.next == (Node.TESTS,)
    assert paused.pause == PauseInfo(reason="weekly at 92%", until=later)
    assert not [e for e in recorder.events if e.startswith("claude")]


def test_a_step_already_running_is_not_interrupted_for_usage(tmp_path: Path) -> None:
    """The guard refuses once the tests are written: that is between steps, so
    the tests commit is kept and the thread waits before the implementation."""
    recorder = fresh(tmp_path)

    def window() -> tuple[bool, str]:
        return "claude:tests" not in recorder.events, WINDOW

    outcome = tick(tmp_path, recorder, may_start=window, resume_at=lambda: UNTIL)

    assert outcome.status == RunStatus.PAUSED
    assert "commit:test" in recorder.events, "the step that was running finished"
    assert position(tmp_path).next == (Node.IMPLEMENT,)

    resumed = tick(tmp_path, recorder, may_start=lambda: (True, "usage fine"))

    assert resumed.status == RunStatus.OPEN
    assert recorder.events.count("claude:tests") == 1, "not written again"
    assert recorder.events.count("claude:impl") == 1
