"""The pipeline runs the fixers between the implementation agent and the `feat:` commit, in a
stubbed build and in one that is not (spec: fixers-run-before-commits)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.stack_runner import FixResult
from tests.factories import activate_with
from tests.graph.branch_fakes import built, prepared
from tests.graph.fixer_fakes import FIXERS, FORMATTED, Formatting
from tests.graph.stub_loop_fakes import stubbed_build
from tests.graph.test_build_path import build
from tests.graph_driver import fresh as fresh_store

SOURCE = "src/x.py"
TESTS_FILE = "tests/test_x.py"
LEAVES = {"claude:tests": TESTS_FILE, "claude:impl": SOURCE}


def test_the_implementation_is_formatted_after_the_agent_and_before_the_commit(
    tmp_path: Path,
) -> None:
    stubbed_build()
    recorder = Formatting(fresh_store(tmp_path).store, leaves=LEAVES)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open", outcome.detail
    events = recorder.events
    assert events[events.index("claude:impl") :][:3] == ["claude:impl", FIXERS, "commit:feat"]
    assert recorder.held_by("feat:")[SOURCE] == FORMATTED


def test_a_build_that_is_not_stubbed_formats_before_its_tests_commit_and_its_implementation(
    tmp_path: Path,
) -> None:
    activate_with(builders={"per_group_commits": False})
    recorder = Formatting(fresh_store(tmp_path).store, leaves=LEAVES)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open", outcome.detail
    assert recorder.events[:6] == [
        "claude:tests",
        FIXERS,
        "commit:test",
        "claude:impl",
        FIXERS,
        "commit:feat",
    ]
    assert recorder.held_by("test:")[TESTS_FILE] == FORMATTED
    assert recorder.held_by("feat:")[SOURCE] == FORMATTED


def test_a_clean_tree_runs_the_fixers_with_nothing_to_change_and_logs_nothing(
    tmp_path: Path,
) -> None:
    stubbed_build()
    recorder = Formatting(fresh_store(tmp_path).store)

    outcome = build(tmp_path, recorder, **recorder.overrides(tmp_path))

    assert outcome.status == "open", outcome.detail
    assert recorder.events.count(FIXERS) >= 2, "once before each commit"
    assert recorder.fixer_lines() == []


def test_a_group_recorded_as_already_built_is_unchanged_by_the_call(tmp_path: Path) -> None:
    calls: list[Path] = []

    def fixers(*, cwd: Path) -> FixResult:
        calls.append(cwd)
        return FixResult()

    silent = {"silent_groups": (1, 2, 3)}
    plain, plain_outcome, _ = built(tmp_path / "plain", **silent)
    recorder, _ = prepared(tmp_path / "fixing", **silent)

    outcome = build(
        tmp_path / "fixing", recorder, **recorder.overrides(tmp_path / "fixing"), run_fixers=fixers
    )

    assert calls, "the fixers were called"
    assert outcome.status == plain_outcome.status == "satisfied", outcome.detail
    assert recorder.subjects == plain.subjects
    assert not [line for line in recorder.logged if "fixers " in line]
