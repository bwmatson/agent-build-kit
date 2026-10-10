"""`abk doctor` notes cassettes waiting for review and warns about one left too long."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli.doctor import Check, run_doctor
from agent_build_kit.config import WorkspaceConfig, dump
from tests.cli.replay_driver import REVIEW_AFTER_RUNS, replay_repo, store
from tests.cli.test_doctor import Answers, which_all
from tests.factories import init_repo
from tests.replay.support import waiting_cassette


def doctor(tmp_path: Path, *, section: bool = True, unreviewed_runs: int = 0) -> list[Check]:
    planning = init_repo(tmp_path / "planning")
    repo, directory = replay_repo(tmp_path / "app", section=section)
    store(
        directory,
        waiting_cassette("tests/test_a.py::test_one", 0),
        waiting_cassette("tests/test_a.py::test_one", 3, path="/v1/other"),
        unreviewed_runs=unreviewed_runs,
    )
    (planning / "abk.yaml").write_text(dump(WorkspaceConfig(repos={"app": repo})))
    return run_doctor(planning / "abk.yaml", run=Answers(), which=which_all)


def replay_checks(checks: list[Check]) -> list[Check]:
    return [check for check in checks if "replay" in check.name or "cassette" in check.name]


def test_some_waiting_is_a_note_that_gives_the_count(tmp_path: Path) -> None:
    [check] = replay_checks(doctor(tmp_path, unreviewed_runs=1))

    assert check.status == "info"
    assert "2" in check.detail
    assert "abk replay review" in check.detail + check.fix


def test_one_unreviewed_past_the_limit_is_a_warning(tmp_path: Path) -> None:
    [check] = replay_checks(doctor(tmp_path, unreviewed_runs=REVIEW_AFTER_RUNS + 1))

    assert check.status == "warn"
    assert "abk replay review" in check.detail + check.fix


def test_one_at_the_limit_is_still_only_a_note(tmp_path: Path) -> None:
    [check] = replay_checks(doctor(tmp_path, unreviewed_runs=REVIEW_AFTER_RUNS))

    assert check.status == "info"


def test_a_repository_with_no_replay_section_has_no_check(tmp_path: Path) -> None:
    assert replay_checks(doctor(tmp_path, section=False, unreviewed_runs=9)) == []
