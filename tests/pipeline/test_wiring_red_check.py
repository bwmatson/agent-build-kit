"""The red check the build runs at the tests commit judges the commit as the push gate does and
is not run again for a commit it has judged (spec: tdd-loop).

Over real git repositories and a real pytest, with the red-check-by-id tests' profile and cases.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.pipeline.check_runner import CheckCache
from agent_build_kit.pipeline.wiring import build_red_check
from agent_build_kit.profiles.base import ToolchainProfile
from tests.factories import commit_files
from tests.pipeline.test_red_check_by_id import SUBJECT, IdProfile, branch_with, source

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
