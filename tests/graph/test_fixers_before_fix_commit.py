"""The pipeline runs the fixers between a checks-loop fix agent and the `fix:` commit, and the
stop rule is kept (spec: fixers-run-before-commits, one-check-and-fix-loop)."""

from __future__ import annotations

from pathlib import Path

from tests.factories import unit
from tests.graph.fixer_fakes import FIXERS, FORMATTED, Formatting
from tests.graph.stub_loop_fakes import stubbed_build
from tests.graph.test_build_path import build, limited
from tests.graph_driver import fresh as fresh_store

SOURCE = "src/x.py"
FAILING = "FAILED tests/test_y.py::test_other - assert 1 == 2"
LINT = "tests/test_x.py:1:8: F401 `os` imported but unused"


def failing_once(tmp_path: Path, **options: object) -> Formatting:
    stubbed_build()
    recorder = Formatting(fresh_store(tmp_path).store, **options)  # type: ignore[arg-type]
    recorder.unit_test_results = [(False, FAILING), (True, "")]
    return recorder


def test_a_fix_agents_unformatted_file_is_committed_formatted_and_the_next_check_is_clean(
    tmp_path: Path,
) -> None:
    recorder = failing_once(tmp_path, leaves={"claude:fix_checks": SOURCE})

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open", outcome.detail
    events = recorder.events
    assert events[events.index("claude:fix_checks") :][:3] == [
        "claude:fix_checks",
        FIXERS,
        "commit:fix",
    ]
    assert f"fix: {unit().title} (checks, round 1)" in recorder.subjects
    assert recorder.held_by("fix:")[SOURCE] == FORMATTED
    assert recorder.formatted_at_check[-1] is True, "the check after the fix found it formatted"


def test_a_round_whose_agent_edits_nothing_and_whose_fixers_change_a_file_is_not_stopped(
    tmp_path: Path,
) -> None:
    recorder = failing_once(tmp_path, surprises={"claude:fix_checks": SOURCE})

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open", outcome.detail
    assert "changed nothing" not in outcome.detail
    assert recorder.held_by("fix:")[SOURCE] == FORMATTED
    assert any("fixers changed 1 file(s)" in line for line in recorder.logged)


def test_a_round_whose_agent_and_fixers_change_nothing_still_stops_the_unit(
    tmp_path: Path,
) -> None:
    limited(max_check_rounds=None)
    stubbed_build()
    recorder = Formatting(fresh_store(tmp_path).store, commits_from_impl=0, unit_test_ok=False)
    recorder.unit_test_output = FAILING

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert "checks failing and fix round 1 changed nothing, before review" in outcome.detail
    assert FIXERS in recorder.events[recorder.events.index("claude:fix_checks") :]


def test_a_stub_check_that_still_fails_after_the_fixers_stops_when_the_agent_edits_nothing(
    tmp_path: Path,
) -> None:
    limited(max_check_rounds=None)
    stubbed_build()
    recorder = Formatting(fresh_store(tmp_path).store, checks=[(False, LINT)], fixes_change=False)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "failed"
    assert "static checks failing and fix round 1 changed nothing" in outcome.detail
    assert recorder.events.index(FIXERS) < recorder.events.index("stub-checks")
