"""A unit-test run that ends at the command's time limit holds its unit for a person (spec:
unit-test-command-limit): no fix agent runs, no fix round is counted and no feedback is saved. It
holds in the checks before review, in the unit-test after a clean move and in the run that
confirms a group already built. A failure that did not reach the limit is handled as before.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.command_limit import SUSPENDED_NOTE
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import RETRY_BY, Cause
from agent_build_kit.pipeline.units import HELD, PLANNED
from packages.worker.tests.graph.test_build_path import FAILING, build, restacked
from packages.worker.tests.graph.test_fresh_base_builds import Moving
from packages.worker.tests.graph.test_remaining_paths import fresh
from tests.factories import unit
from tests.graph.branch_fakes import UNIT, prepared

OLD_BASE = "old-base-sha"
TIME_LIMIT = "time limit"
RETRY_NOTE = "time limit: runs once more by itself"
NOTE = "unit-test command timed out after 5400 seconds and was aborted"
# What the runner hands back: the command and its exit status, the run's own output, the note last.
TIMED_OUT = (
    f"$ uv run pytest -n 2 -q (exit 124)\n...... [ 41%]\nFatal Python error: Aborted\n\n{NOTE}\n"
)
PARTIAL = (
    f"$ uv run pytest (exit 124)\nFAILED tests/test_widget.py::test_renders_the_label\n\n{NOTE}\n"
)


def held_for_a_person(recorder: Any, unit_id: str = UNIT) -> None:
    stored = recorder.store.get(unit_id)
    assert (stored.state, stored.cause) == (HELD, Cause.NEEDS_HUMAN)
    assert "5400" in stored.note
    assert stored.feedback == "", "nothing is saved for a fix agent"


def test_the_checks_hold_the_unit_and_run_no_fix_agent(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, unit_test_ok=False)
    recorder.store.record_retry(unit().id, TIME_LIMIT, RETRY_NOTE)
    recorder.unit_test_output = TIMED_OUT

    outcome = build(tmp_path, recorder)

    assert outcome.status == RunStatus.HELD
    held_for_a_person(recorder, unit().id)
    assert recorder.events.count("unit-test") == 1
    assert "claude:fix_checks" not in recorder.events
    assert "review" not in recorder.events and "push" not in recorder.events


def test_a_run_that_failed_tests_and_then_reached_the_limit_is_a_timeout_too(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, unit_test_ok=False)
    recorder.store.record_retry(unit().id, TIME_LIMIT, RETRY_NOTE)
    recorder.unit_test_output = PARTIAL

    outcome = build(tmp_path, recorder)

    assert outcome.status == RunStatus.HELD
    assert "claude:fix_checks" not in recorder.events


def test_a_timeout_after_a_fix_round_clears_the_failure_that_round_answered(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.store.record_retry(unit().id, TIME_LIMIT, RETRY_NOTE)
    recorder.unit_test_results = [(False, FAILING), (False, TIMED_OUT)]

    outcome = build(tmp_path, recorder)

    assert outcome.status == RunStatus.HELD
    assert recorder.events.count("claude:fix_checks") == 1
    assert recorder.store.get(unit().id).feedback == "", "a requeue must not rework it"


def test_a_failure_before_the_limit_is_saved_and_fixed_as_before(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    recorder.unit_test_results = [(False, FAILING), (True, "")]

    outcome = build(tmp_path, recorder)

    assert outcome.status == "open"
    assert recorder.events.count("claude:fix_checks") == 1


def test_the_unit_test_after_a_clean_move_holds_the_unit_and_does_not_restack_again(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.store.record_retry(unit().id, TIME_LIMIT, RETRY_NOTE)
    recorder.unit_test_results = [(True, ""), (False, TIMED_OUT)]
    moving = Moving(recorder, restacked(old_base=OLD_BASE))

    outcome = build(tmp_path, recorder, **moving.overrides())

    assert outcome.status == RunStatus.HELD
    held_for_a_person(recorder, unit().id)
    after = recorder.events[recorder.events.index("moved") :]
    assert "push" not in after and "claude:fix_checks" not in after


def test_a_group_already_built_whose_run_times_out_holds_the_unit_and_is_not_unpaired(
    tmp_path: Path,
) -> None:
    recorder, _ = prepared(tmp_path, silent_groups=(1, 2, 3))
    recorder.store.record_retry(UNIT, TIME_LIMIT, RETRY_NOTE)
    overrides: dict[str, Any] = recorder.overrides(tmp_path)
    overrides.update(run_unit_test=lambda **kwargs: (False, TIMED_OUT))

    outcome = build(tmp_path, recorder, **overrides)

    assert outcome.status == RunStatus.HELD
    held_for_a_person(recorder)


def retries(recorder: Any, cause: str) -> list[dict[str, Any]]:
    return [
        entry
        for entry in recorder.store.history(unit().id)
        if entry.get("by") == RETRY_BY and str(entry.get("note", "")).startswith(cause)
    ]


def test_a_first_time_limit_in_the_checks_puts_the_unit_back_to_run_once_more(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, unit_test_ok=False)
    recorder.unit_test_output = TIMED_OUT

    build(tmp_path, recorder)

    stored = recorder.store.get(unit().id)
    assert stored.state == PLANNED
    assert "once more by itself" in stored.note
    assert stored.feedback == "", "nothing is saved for a fix agent"
    assert "claude:fix_checks" not in recorder.events
    assert len(retries(recorder, TIME_LIMIT)) == 1


def test_a_first_suspended_twice_stop_puts_the_unit_back_to_run_once_more(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path, unit_test_ok=False)
    recorder.unit_test_output = SUSPENDED_NOTE

    build(tmp_path, recorder)

    stored = recorder.store.get(unit().id)
    assert stored.state == PLANNED
    assert "once more by itself" in stored.note
    assert "claude:fix_checks" not in recorder.events
    assert len(retries(recorder, "suspended")) == 1
    assert retries(recorder, TIME_LIMIT) == []


def test_a_first_time_limit_in_the_unit_test_after_a_clean_move_runs_once_more(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.unit_test_results = [(True, ""), (False, TIMED_OUT)]
    moving = Moving(recorder, restacked(old_base=OLD_BASE))

    build(tmp_path, recorder, **moving.overrides())

    assert recorder.store.get(unit().id).state == PLANNED
    assert len(retries(recorder, TIME_LIMIT)) == 1
    assert "push" not in recorder.events[recorder.events.index("moved") :]


def test_a_first_time_limit_in_a_group_already_built_runs_once_more(tmp_path: Path) -> None:
    recorder, _ = prepared(tmp_path, silent_groups=(1, 2, 3))
    overrides: dict[str, Any] = recorder.overrides(tmp_path)
    overrides.update(run_unit_test=lambda **kwargs: (False, TIMED_OUT))

    build(tmp_path, recorder, **overrides)

    assert recorder.store.get(UNIT).state == PLANNED
    assert len(retries(recorder, TIME_LIMIT)) == 1


def test_a_spent_retry_is_not_taken_again_and_writes_no_second_entry(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, unit_test_ok=False)
    recorder.store.record_retry(unit().id, TIME_LIMIT, RETRY_NOTE)
    recorder.unit_test_output = TIMED_OUT

    build(tmp_path, recorder)

    assert len(retries(recorder, TIME_LIMIT)) == 1


def test_a_spent_retry_for_another_cause_does_not_hold_the_unit(tmp_path: Path) -> None:
    recorder = fresh(tmp_path, unit_test_ok=False)
    recorder.store.record_retry(unit().id, "suspended", "suspended: runs once more by itself")
    recorder.unit_test_output = TIMED_OUT

    build(tmp_path, recorder)

    assert recorder.store.get(unit().id).state == PLANNED
