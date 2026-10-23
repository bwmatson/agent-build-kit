"""A group its agents left nothing to commit for is recorded only when the whole repository's
unit tests pass on the tree (spec: built-group-recorded-as-empty-pair). Each case that stops is
built beside a passing one, so the file fails while nothing is recorded."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

from agent_build_kit.pipeline.flakes import FlakeFound
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource
from agent_build_kit.pipeline.units import FAILED, SATISFIED
from tests.conftest import make_installation
from tests.environment_fakes import FakeEnvironment
from tests.graph.branch_fakes import (
    UNIT,
    built,
    built_after_a_pair,
    messages,
    prepared,
    recorded_pair,
    subjects,
    titled,
)
from tests.graph.test_build_path import build
from tests.graph.test_flake_parking import FLAKE

PAIR_3 = ["test: G3", "feat: G3"]
PAIR = "the branch holds no tests and implementation pair for group 4 (G4)"
FAILURE = "E   AssertionError: the marker is not registered"


def passing_beside(tmp_path: Path) -> None:
    """The same unit with passing tests, which records the pair."""
    _, _, repo = built_after_a_pair(tmp_path / "passing")
    recorded_pair(repo)


def test_failing_whole_repo_tests_record_nothing_and_stop_the_unit_with_the_pair_message(
    tmp_path: Path,
) -> None:
    passing_beside(tmp_path)
    recorder, repo = prepared(
        tmp_path / "failing",
        groups={"add-marker": titled(3, 4)},
        silent_groups=(4,),
        unit_test_ok=False,
    )
    recorder.unit_test_output = FAILURE

    outcome = build(tmp_path / "failing", recorder, **recorder.overrides(tmp_path / "failing"))

    assert outcome.status == "failed"
    assert PAIR in outcome.detail
    assert recorder.events.count("unit-test:whole_repo") == 1
    assert subjects(repo) == [*PAIR_3, "test: G4"], "only the feat: is withheld"
    assert any(FAILURE in line for line in recorder.logged), recorder.logged
    stored = recorder.store.get(UNIT)
    assert stored.feedback_source == FeedbackSource.UNIT_TEST
    assert FAILURE in stored.feedback
    assert stored.state != SATISFIED
    assert "review" not in recorder.events


def test_a_flake_found_on_that_run_counts_as_the_same_failure(tmp_path: Path) -> None:
    passing_beside(tmp_path)
    recorder, repo = prepared(
        tmp_path / "flaking", groups={"add-marker": titled(3, 4)}, silent_groups=(4,)
    )

    def flaking(*, cwd: Path, base: str = "main", whole_repo: bool = False, **_: Any) -> NoReturn:
        recorder.events.append("unit-test:whole_repo" if whole_repo else "unit-test")
        raise FlakeFound((FLAKE,))

    overrides: dict[str, Any] = {
        **recorder.overrides(tmp_path / "flaking"),
        "run_unit_test": flaking,
    }
    outcome = build(tmp_path / "flaking", recorder, **overrides)

    assert outcome.status == "failed"
    assert PAIR in outcome.detail
    assert subjects(repo) == [*PAIR_3, "test: G4"]
    stored = recorder.store.get(UNIT)
    assert stored.feedback_source == FeedbackSource.UNIT_TEST
    assert FLAKE.output.strip() in stored.feedback


def test_a_broken_environment_blocks_the_unit_and_is_not_read_as_missing_work(
    tmp_path: Path,
) -> None:
    passing_beside(tmp_path)
    env = FakeEnvironment(tmp_path / "control")
    make_installation(tmp_path / "meta", environment=env.config())
    (tmp_path / "meta" / "manifest.toml").write_text("name = 1\n")
    recorder, repo = prepared(tmp_path, groups={"add-marker": titled(3, 4)}, silent_groups=(4,))

    def breaks_the_environment(*, cwd: Path, base: str = "main", whole_repo: bool = False, **_):
        recorder.events.append("unit-test:whole_repo" if whole_repo else "unit-test")
        env.break_it()
        return False, "error: executable `ruff` was not found"

    overrides: dict[str, Any] = {
        **recorder.overrides(tmp_path),
        "run_unit_test": breaks_the_environment,
    }
    outcome = build(tmp_path, recorder, **overrides)

    assert outcome.status == RunStatus.FAILED
    assert PAIR not in outcome.detail
    stored = recorder.store.get(UNIT)
    assert (stored.state, stored.cause) == (FAILED, Cause.ENVIRONMENT)
    assert stored.feedback == "", "nothing for an agent to fix is saved"
    assert subjects(repo) == [*PAIR_3, "test: G4"]


def test_a_real_tests_commit_with_no_implementation_stops_when_the_suite_fails_and_records_nothing(
    tmp_path: Path,
) -> None:
    passing_beside(tmp_path)
    recorder, outcome, repo = built(
        tmp_path / "stubs",
        groups={"add-marker": titled(3, 4)},
        no_commit_for="4",
        unit_test_ok=False,
    )

    assert outcome.status == "failed"
    assert PAIR in outcome.detail
    assert subjects(repo) == [*PAIR_3, "test: G4"]
    assert not any("Already-built" in message for message in messages(repo)[-1:])
    assert recorder.events.count("unit-test:whole_repo") == 1


def test_a_real_tests_commit_with_no_implementation_is_completed_with_an_empty_feat_when_it_passes(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(
        tmp_path, groups={"add-marker": titled(3, 4)}, no_commit_for="4"
    )

    assert outcome.status == "open", outcome.detail
    assert subjects(repo) == [*PAIR_3, "test: G4", "feat: G4"]
    assert "Already-built: yes" in messages(repo)[-1]
    assert "Already-built" not in messages(repo)[-2]
    assert recorder.events.count("unit-test:whole_repo") == 1
