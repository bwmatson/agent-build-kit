"""The push gate for a stubbed build (spec: test-stubs, per-group-commits).

At each tests commit it runs the clean command with types and reads the red run as stubbed,
requires the pairs, and judges every tests commit on its own. A build that is not stubbed runs
what it ran before.
"""

from __future__ import annotations

from pathlib import Path

from tests.stub_gate_support import (
    TYPE_ERROR,
    ModeProfile,
    commit_feat,
    commit_tests,
    judged,
    repo,  # noqa: F401  (the fixture)
    two_pairs,
)


def test_a_stubbed_gate_runs_types_and_the_stubbed_red_reading_at_each_tests_commit(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    two_pairs(repo)
    profile = ModeProfile()

    assert judged(repo, profile, stubbed=True) == []

    assert profile.cleans == [True, True]
    assert profile.reads == [True, True]


def test_a_tests_commit_that_fails_types_is_refused_naming_it_and_the_checker_output(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    first, second = two_pairs(repo)

    problems = judged(repo, ModeProfile(bad_types="tests/test_b.py"), stubbed=True)

    assert problems
    assert all(second[:8] in problem for problem in problems)
    assert any(TYPE_ERROR in problem for problem in problems)
    assert not any(first[:8] in problem for problem in problems)


def test_the_second_groups_red_is_judged_on_its_own_when_the_first_is_correct(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    first, second = two_pairs(repo)

    problems = judged(repo, ModeProfile(bad_red="tests/test_b.py"), stubbed=True)

    assert problems
    assert all(second[:8] in problem for problem in problems)
    assert any("AttributeError" in problem for problem in problems)
    assert not any(first[:8] in problem for problem in problems)


def test_a_tests_commit_followed_by_another_is_refused_only_for_a_stubbed_build(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    commit_tests(repo, "one", "a")
    commit_tests(repo, "two", "b")
    commit_feat(repo, "two", "b")

    stubbed = judged(repo, ModeProfile(), stubbed=True)
    before = judged(repo, ModeProfile())

    assert any("test: two" in problem for problem in stubbed)
    assert not any("test: two" in problem for problem in before), before


def test_a_build_that_is_not_stubbed_runs_without_types_and_with_the_plain_red_reading(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    two_pairs(repo)
    profile = ModeProfile(bad_types="tests/test_b.py", bad_red="tests/test_b.py")

    assert judged(repo, profile) == []
    assert profile.cleans == [False, False]
    assert profile.reads == [False, False]

    assert judged(repo, ModeProfile(bad_types="tests/test_b.py"), stubbed=True)
