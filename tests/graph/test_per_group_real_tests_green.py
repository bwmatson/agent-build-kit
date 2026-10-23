"""A group with real tests whose implementation step changes nothing is completed with an empty
`feat:` marked `Already-built: yes` when the whole repository's unit tests pass, and stops the
unit as before when they do not (spec: built-group-recorded-as-empty-pair). Each case that
records nothing is built beside the one that does, so the file fails while nothing is recorded."""

from __future__ import annotations

from pathlib import Path
from typing import Any, NoReturn

from agent_build_kit.pipeline.flakes import FlakeFound
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource
from agent_build_kit.pipeline.units import FAILED
from tests.conftest import make_installation
from tests.environment_fakes import FakeEnvironment
from tests.graph.branch_fakes import (
    ACCOUNT,
    UNIT,
    built,
    files_in,
    messages,
    prepared,
    subjects,
    titled,
)
from tests.graph.test_build_path import build
from tests.graph.test_flake_parking import FLAKE

GROUPS = {"add-marker": titled(11, 12, 13)}
PAIR_11 = ["test: G11", "feat: G11"]
PAIR = "the branch holds no tests and implementation pair for group 12 (G12)"
SENTENCE = (
    "The tests for this group pass without further implementation: "
    "the implementation already exists."
)
HEADING = "Already built, the builder's account:"


def recorded_beside(tmp_path: Path) -> None:
    """The same unit with passing tests, which completes group 12 with an empty `feat:`."""
    recorder, outcome, repo = built(
        tmp_path / "passing", groups=GROUPS, no_commit_for="12", accounts={"12": ACCOUNT}
    )
    assert outcome.status == "open", outcome.detail
    assert subjects(repo) == [*PAIR_11, "test: G12", "feat: G12", "test: G13", "feat: G13"]
    assert recorder.events.count("unit-test:whole_repo") == 1


def test_real_tests_that_pass_with_no_implementation_change_get_an_empty_marked_feat_commit(
    tmp_path: Path,
) -> None:
    recorder, outcome, repo = built(
        tmp_path, groups=GROUPS, no_commit_for="12", accounts={"12": ACCOUNT}
    )

    assert outcome.status == "open", outcome.detail
    assert subjects(repo) == [*PAIR_11, "test: G12", "feat: G12", "test: G13", "feat: G13"]
    assert files_in(repo, "HEAD~3") != [], "group 12's tests commit is the real one"
    assert files_in(repo, "HEAD~2") == []
    feat = messages(repo)[-3]
    assert f"Unit: {UNIT}" in feat and "Already-built: yes" in feat
    assert "Already-built" not in messages(repo)[-4]
    assert feat.index(SENTENCE) < feat.index(f"{HEADING}\n{ACCOUNT}")
    assert recorder.events.count("unit-test:whole_repo") == 1
    assert recorder.events.count("claude:tests") == 3, "the unit goes on to group 13"


def test_the_same_tests_failing_stop_the_unit_with_the_pair_message_and_record_nothing(
    tmp_path: Path,
) -> None:
    recorded_beside(tmp_path)
    recorder, repo = prepared(
        tmp_path / "failing", groups=GROUPS, no_commit_for="12", unit_test_ok=False
    )
    recorder.unit_test_output = "E   NotImplementedError"

    outcome = build(tmp_path / "failing", recorder, **recorder.overrides(tmp_path / "failing"))

    assert outcome.status == "failed"
    assert PAIR in outcome.detail
    assert subjects(repo) == [*PAIR_11, "test: G12"]
    assert "Already-built" not in messages(repo)[-1]
    stored = recorder.store.get(UNIT)
    assert stored.feedback_source == FeedbackSource.UNIT_TEST
    assert "NotImplementedError" in stored.feedback
    assert "review" not in recorder.events


def test_a_flake_found_on_that_run_counts_as_the_failure(tmp_path: Path) -> None:
    recorded_beside(tmp_path)
    recorder, repo = prepared(tmp_path / "flaking", groups=GROUPS, no_commit_for="12")

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
    assert subjects(repo) == [*PAIR_11, "test: G12"]
    assert recorder.store.get(UNIT).feedback_source == FeedbackSource.UNIT_TEST


def test_a_broken_environment_blocks_the_unit_and_is_not_read_as_missing_work(
    tmp_path: Path,
) -> None:
    recorded_beside(tmp_path)
    env = FakeEnvironment(tmp_path / "control")
    make_installation(tmp_path / "meta", environment=env.config())
    (tmp_path / "meta" / "manifest.toml").write_text("name = 1\n")
    recorder, repo = prepared(tmp_path, groups=GROUPS, no_commit_for="12")

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
    assert subjects(repo) == [*PAIR_11, "test: G12"]


def test_real_tests_with_an_implementation_that_changes_a_file_get_the_normal_feat_commit(
    tmp_path: Path,
) -> None:
    recorded_beside(tmp_path)
    recorder, _, repo = built(tmp_path / "normal", groups=GROUPS)

    assert subjects(repo)[2:4] == ["test: G12", "feat: G12"]
    assert files_in(repo, "HEAD~3") != [] and files_in(repo, "HEAD~2") != []
    assert not any("Already-built" in message for message in messages(repo))
    assert "unit-test:whole_repo" not in recorder.events
    assert "commit_built:feat" not in recorder.events
