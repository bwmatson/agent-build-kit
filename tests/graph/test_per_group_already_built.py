"""A stubbed unit whose branch holds no commit of its own is satisfied when the unit tests pass,
as a build that is not stubbed is (spec: already-built-unit-satisfied). The agents write and
commit nothing for any group, as when the work is already on the base."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import FeedbackSource
from agent_build_kit.pipeline.units import PLANNED, SATISFIED, branch_name
from tests.factories import unit
from tests.graph.branch_fakes import UNIT, agent_calls, built, prepared, subjects
from tests.graph.test_build_path import build

SILENT = {"silent_groups": (1, 2, 3)}
NOTE = "nothing to add and unit-test passes — satisfied"


def test_a_stubbed_unit_that_adds_nothing_and_passes_its_tests_is_satisfied(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(tmp_path, **SILENT)

    assert outcome.status == "satisfied", outcome.detail
    assert recorder.store.get(UNIT).state == SATISFIED
    assert any(NOTE in line for line in recorder.logged), recorder.logged
    assert agent_calls(recorder.events) == ["claude:tests", "claude:impl"] * 3
    assert recorder.events.count("unit-test:whole_repo") == 1
    for step in ("review", "push", "pr"):
        assert step not in recorder.events
    assert subjects(repo) == [], "the branch holds no commit"


def test_the_same_unit_with_failing_unit_tests_fails_and_saves_the_output_as_feedback(
    tmp_path: Path,
) -> None:
    recorder, repo = prepared(tmp_path, unit_test_ok=False, **SILENT)
    recorder.unit_test_output = "E   ImportError: cannot import name 'geo'"

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert "unit-test failed" in outcome.detail
    stored = recorder.store.get(UNIT)
    assert stored.state != SATISFIED
    assert stored.feedback_source == FeedbackSource.UNIT_TEST
    assert "ImportError" in stored.feedback
    assert "push" not in recorder.events and recorder.prs == {}
    assert subjects(repo) == []


def test_a_satisfied_unit_with_a_pull_request_recorded_has_it_closed(tmp_path: Path) -> None:
    recorder, _ = prepared(tmp_path, **SILENT)
    recorder.store.set_state(UNIT, PLANNED, pr=4, branch=branch_name(unit()))

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "satisfied", outcome.detail
    assert recorder.store.get(UNIT).state == SATISFIED
    assert [(unit_id, pr) for unit_id, pr, _ in recorder.closed] == [(UNIT, 4)]
    assert "push" not in recorder.events and "pr" not in recorder.events
