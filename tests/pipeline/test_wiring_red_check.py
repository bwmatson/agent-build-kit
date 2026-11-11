"""The red check the build runs at the tests commit judges the commit as the push gate does and
is not run again for a commit it has judged (spec: tdd-loop).

Over real git repositories and a real pytest, with the red-check-by-id tests' profile and cases.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.pipeline.check_runner import CheckCache
from agent_build_kit.pipeline.wiring import build_red_check
from agent_build_kit.profiles.base import ToolchainProfile
from tests.factories import commit_files
from tests.pipeline.test_red_check_by_id import NEW, SUBJECT, IdProfile, branch_with, source
from tests.redaction_fakes import SECRET, known

COLLECTION_ERROR = (
    "import module_that_does_not_exist\n\n\ndef test_new():\n    raise AssertionError()\n"
)


def checker(profile: IdProfile, cache: CheckCache | None = None) -> Callable[..., tuple[bool, str]]:
    return build_red_check(profile=cast(ToolchainProfile, profile), cache=cache)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return branch_with(tmp_path, {SUBJECT: source("old_case")})


def test_a_new_test_that_fails_with_an_assertion_is_accepted(repo: Path) -> None:
    commit_files(repo, "test: the cases", {SUBJECT: source("new_failing_case")})

    ok, reason = checker(IdProfile())(cwd=repo)

    assert ok, reason


def test_a_new_test_that_passes_is_rejected_with_the_reason(repo: Path) -> None:
    commit_files(repo, "test: the cases", {SUBJECT: source("new_passing_case")})

    ok, reason = checker(IdProfile())(cwd=repo)

    assert not ok
    assert "passed" in reason


def test_the_red_check_writes_its_run_to_the_log_it_is_given(repo: Path) -> None:
    commit_files(repo, "test: the cases", {SUBJECT: source("new_failing_case")})
    lines: list[str] = []
    check = build_red_check(profile=cast(ToolchainProfile, IdProfile()), log=lines.append)

    check(cwd=repo)

    logged = "\n".join(lines)
    assert "-m pytest" in logged
    assert NEW in logged
    assert "exit code 1" in logged


def test_a_test_that_cannot_be_collected_is_rejected(repo: Path) -> None:
    commit_files(repo, "test: the cases", {SUBJECT: COLLECTION_ERROR})

    ok, reason = checker(IdProfile())(cwd=repo)

    assert not ok
    assert reason


def test_a_commit_already_judged_is_not_run_again(repo: Path, tmp_path: Path) -> None:
    commit_files(repo, "test: the cases", {SUBJECT: source("new_failing_case")})
    profile = IdProfile()
    check = checker(profile, CheckCache(tmp_path / "cache.json"))

    first = check(cwd=repo)
    asked = len(profile.asked)
    second = check(cwd=repo)

    assert asked == 1
    assert len(profile.asked) == asked, "the second call ran nothing"
    assert second == first


def test_a_rejection_is_remembered_as_one(repo: Path, tmp_path: Path) -> None:
    commit_files(repo, "test: the cases", {SUBJECT: source("new_passing_case")})
    profile = IdProfile()
    check = checker(profile, CheckCache(tmp_path / "cache.json"))

    check(cwd=repo)
    ok, reason = check(cwd=repo)

    assert len(profile.asked) == 1
    assert not ok
    assert reason


def test_a_repeat_of_a_rejected_commit_is_answered_with_the_earlier_reasons(
    repo: Path, tmp_path: Path
) -> None:
    commit_files(repo, "test: the cases", {SUBJECT: source("new_passing_case")})
    profile = IdProfile()
    check = checker(profile, CheckCache(tmp_path / "cache.json"))

    _, first = check(cwd=repo)
    ok, again = check(cwd=repo)

    assert not ok
    assert len(profile.asked) == 1
    assert "passed" in again
    assert first.splitlines()[0].split(": ", 1)[1] in again
    assert "not run again" in again


def test_a_cached_rejection_still_reads_as_false_to_a_reader_of_the_plain_result(
    repo: Path, tmp_path: Path
) -> None:
    commit_files(repo, "test: the cases", {SUBJECT: source("new_passing_case")})
    cache = CheckCache(tmp_path / "cache.json")
    checker(IdProfile(), cache)(cwd=repo)

    stored = json.loads((tmp_path / "cache.json").read_text())

    results = {key: value for key, value in stored.items() if not key.endswith(":reasons")}
    assert list(results.values()) == [False]
    assert any(key.endswith(":reasons") for key in stored)


class LeakingProfile(IdProfile):
    """A reading whose rejection quotes a secret."""

    def interpret_red(
        self, output: str, exit_code: int, *, stubbed: bool = False
    ) -> tuple[bool, list[str]]:
        return False, [f"the run printed {SECRET}"]


def test_the_reasons_a_repeat_is_answered_with_pass_through_redaction(
    repo: Path, tmp_path: Path
) -> None:
    commit_files(repo, "test: the cases", {SUBJECT: source("new_failing_case")})
    check = checker(LeakingProfile(), CheckCache(tmp_path / "cache.json"))

    with known():
        check(cwd=repo)
        _, again = check(cwd=repo)

    assert "the run printed" in again
    assert SECRET not in again
