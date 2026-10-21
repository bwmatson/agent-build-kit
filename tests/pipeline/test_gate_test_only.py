"""The push gate at a test-only group's tests commit: lint, format and types, and no red run
(spec: a-test-only-group-commits-no-pair).

Over real git repositories, with the toolchain's commands scripted by `ModeProfile`.
"""

from __future__ import annotations

from pathlib import Path

from tests.stub_gate_support import (
    TYPE_ERROR,
    ModeProfile,
    commit_feat,
    commit_tests,
    judged,
    plan,
    repo,  # noqa: F401  (the fixture)
)

LIVE_TESTS = "import pytest\n\n\n@pytest.mark.local_stack\ndef test_drive(): assert False\n"


class RedProfile(ModeProfile):
    """`ModeProfile` whose red run is read as the toolchain reads it: a file named `test_pass`
    passes at its tests commit, and a `test_drive` or `test_live` file is the live-stack kind
    whose run collects nothing, none of which shows a test failing."""

    def __init__(self, *, bad_types: str = "") -> None:
        super().__init__(bad_types=bad_types)
        self.red_files: list[list[str]] = []  # the files of each red command asked for

    def red_command(self, files: list[str]) -> str:
        self.red_files.append(files)
        return f"echo '{' '.join(files)}'; exit {0 if 'test_pass' in ' '.join(files) else 1}"

    def interpret_red(
        self, output: str, exit_code: int, *, stubbed: bool = False
    ) -> tuple[bool, list[str]]:
        self.reads.append(stubbed)
        if exit_code == 0:
            return False, ["nothing failed at the tests commit"]
        if "test_drive" in output or "test_live" in output:
            return False, ["no tests ran at the tests commit, so nothing was shown to fail"]
        return True, []


def test_a_test_only_commit_runs_the_clean_command_with_types_and_no_red_run(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    commit_tests(repo, "A", "a")
    commit_feat(repo, "A", "a")
    commit_tests(repo, "Drive", "drive", LIVE_TESTS)
    profile = RedProfile()

    problems = judged(repo, profile, stubbed=True, groups=plan(("A", False), ("Drive", True)))

    assert problems == []
    assert profile.cleans == [True, True]
    assert profile.red_files == [["tests/test_a.py"]]
    assert profile.reads == [True]


def test_an_ordinary_group_whose_tests_pass_at_its_tests_commit_is_still_refused(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    passing = commit_tests(repo, "A", "pass", "def test_x(): assert True\n")
    commit_feat(repo, "A", "pass")
    commit_tests(repo, "Drive", "drive", LIVE_TESTS)

    problems = judged(repo, RedProfile(), stubbed=True, groups=plan(("A", False), ("Drive", True)))

    assert any(passing[:8] in p and "nothing failed at the tests commit" in p for p in problems)
    assert len(problems) == 1


def test_an_ordinary_groups_live_stack_only_commit_is_judged_by_the_red_run(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    live = commit_tests(repo, "Live", "live", LIVE_TESTS)
    commit_feat(repo, "Live", "live")

    problems = judged(repo, RedProfile(), stubbed=True, groups=plan(("Live", False)))

    assert any(live[:8] in p and "no tests ran" in p for p in problems), problems


def test_a_test_only_commit_that_fails_the_type_check_is_refused_naming_the_commit(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    commit_tests(repo, "A", "a")
    commit_feat(repo, "A", "a")
    drive = commit_tests(repo, "Drive", "drive", LIVE_TESTS)

    problems = judged(
        repo,
        RedProfile(bad_types="tests/test_drive.py"),
        stubbed=True,
        groups=plan(("A", False), ("Drive", True)),
    )

    assert problems
    assert all(drive[:8] in problem for problem in problems)
    assert any(TYPE_ERROR in problem for problem in problems)
