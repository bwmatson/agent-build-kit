"""A unit stopped in the stub check loop resumes in the loop (spec: stub-check-loop)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import FeedbackSource
from tests.graph.stub_loop_fakes import StubLoop, stubbed_build
from tests.graph.test_build_path import build, limited
from tests.graph_driver import fresh as fresh_store
from tests.runner_fakes import Killed

UNIT = "add-marker/1"
SAVED = "STUB-OUTPUT-0"


def looping(tmp_path: Path, **options) -> StubLoop:
    stubbed_build()
    return StubLoop(fresh_store(tmp_path).store, **options)


def test_a_unit_stopped_in_the_loop_has_its_output_saved_under_a_source_of_its_own(
    tmp_path: Path,
) -> None:
    limited(max_check_rounds=0)
    recorder = looping(tmp_path, checks=[(False, SAVED)])

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    stored = recorder.store.get(UNIT)
    assert SAVED in stored.feedback
    assert stored.feedback_source is FeedbackSource.STUB_CHECKS


def test_a_requeue_goes_to_the_test_step_and_the_next_agent_call_is_the_fix(
    tmp_path: Path,
) -> None:
    recorder = looping(tmp_path, checks=[(False, SAVED), (True, "")])
    recorder.asked = 1  # the checks that failed ran in the stopped run
    recorder.store.set_feedback(UNIT, SAVED, source=FeedbackSource.STUB_CHECKS)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open"
    assert recorder.events[:4] == ["claude:fix_stub", "stub-checks", "commit:test", "claude:impl"]
    assert "claude:rework" not in recorder.events
    assert "claude:tests" not in recorder.events, "the tests were written before the stop"
    assert SAVED in recorder.fix_prompts[0]


def test_a_run_killed_in_a_fix_resumes_at_the_fix_with_the_rounds_counted(
    tmp_path: Path,
) -> None:
    limited(max_check_rounds=2)
    outputs = [(False, f"STUB-OUTPUT-{n}") for n in range(4)]
    recorder = looping(tmp_path, checks=outputs, kill_in_fix=2)

    with pytest.raises(Killed):
        build(tmp_path, recorder, **recorder.overrides(tmp_path))
    assert recorder.store.get(UNIT).feedback_source is FeedbackSource.STUB_CHECKS
    killed_at = len(recorder.events)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    resumed = recorder.events[killed_at:]
    assert resumed[0] == "claude:fix_stub", "back in the fix, not in the tests"
    assert recorder.events.count("claude:tests") == 1
    assert outcome.status == "failed"
    assert resumed.count("claude:fix_stub") == 1, "the first fix is counted, so one is left"
    assert recorder.events.count("stub-checks") == 3


def test_ordinary_review_feedback_still_goes_to_rework_and_a_stop_in_the_loop_does_not(
    tmp_path: Path,
) -> None:
    reviewed = looping(tmp_path / "review")
    reviewed.store.set_feedback(UNIT, "rename it", source=FeedbackSource.REVIEW)
    stopped = looping(tmp_path / "stopped", checks=[(False, SAVED), (True, "")])
    stopped.asked = 1
    stopped.store.set_feedback(UNIT, SAVED, source=FeedbackSource.STUB_CHECKS)

    build(tmp_path / "review", reviewed, **reviewed.overrides(tmp_path / "review"))
    build(tmp_path / "stopped", stopped, **stopped.overrides(tmp_path / "stopped"))

    assert reviewed.events[0] == "claude:rework"
    assert "claude:fix_stub" not in reviewed.events
    assert stopped.events[:2] == ["claude:fix_stub", "stub-checks"]
    assert "claude:rework" not in stopped.events
