"""The commit-order check's paired mode given the unit's groups: a test-only group's lone
`test:` commit is accepted and nothing else is (spec: a-test-only-group-commits-no-pair).

Over real git repositories in tmp_path, because the rules are about commits and diffs.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.commit_order import (
    check_structure,
    commits_of_test_only_groups,
)
from tests.stub_gate_support import (
    commit_feat,
    commit_tests,
    plan,
    repo,  # noqa: F401  (the fixture)
)


def test_a_lone_tests_commit_of_a_last_test_only_group_passes(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "A", "a")
    commit_feat(repo, "A", "a")
    commit_tests(repo, "Drive", "drive")

    problems = check_structure(
        repo, "main", paired=True, groups=plan(("A", False), ("Drive", True))
    )

    assert problems == []


def test_a_lone_tests_commit_of_an_ordinary_group_is_refused_naming_both_titles(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "A", "a")
    commit_feat(repo, "A", "a")
    commit_tests(repo, "B", "b")

    problems = check_structure(repo, "main", paired=True, groups=plan(("A", False), ("B", False)))

    assert any("test: B" in problem and "feat: B" in problem for problem in problems), problems


def test_a_test_only_commit_in_the_middle_is_not_two_tests_commits_in_a_row(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "A", "a")
    commit_feat(repo, "A", "a")
    commit_tests(repo, "Drive", "drive")
    commit_tests(repo, "C", "c")
    commit_feat(repo, "C", "c")

    problems = check_structure(
        repo, "main", paired=True, groups=plan(("A", False), ("Drive", True), ("C", False))
    )

    assert problems == []


def test_tests_followed_by_another_title_is_refused_naming_both_when_not_test_only(
    repo: Path,  # noqa: F811 — fixture
) -> None:
    commit_tests(repo, "B", "b")
    commit_feat(repo, "C", "c")

    problems = check_structure(repo, "main", paired=True, groups=plan(("B", False), ("C", False)))

    assert any("test: B" in problem and "feat: C" in problem for problem in problems), problems


def test_a_test_only_commit_followed_by_a_fix_commit_passes(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "A", "a")
    commit_feat(repo, "A", "a")
    commit_tests(repo, "Drive", "drive")
    commit_feat(repo, "fix: the route", "fixed").strip()

    problems = check_structure(
        repo, "main", paired=True, groups=plan(("A", False), ("Drive", True))
    )

    assert problems == []


def test_two_groups_with_one_title_are_told_apart_by_position(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "Same", "a")
    commit_feat(repo, "Same", "a")
    commit_tests(repo, "Same", "b")

    accepted = check_structure(
        repo, "main", paired=True, groups=plan(("Same", False), ("Same", True))
    )
    refused = check_structure(
        repo, "main", paired=True, groups=plan(("Same", True), ("Same", False))
    )

    assert accepted == []
    assert any("test: Same" in problem for problem in refused), refused


def test_a_branch_of_only_test_only_groups_needs_no_implementation_commit(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "One", "one")
    commit_tests(repo, "Two", "two")

    problems = check_structure(repo, "main", paired=True, groups=plan(("One", True), ("Two", True)))

    assert problems == []


def test_the_same_branch_with_one_group_not_test_only_is_refused(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "One", "one")
    commit_tests(repo, "Two", "two")

    problems = check_structure(
        repo, "main", paired=True, groups=plan(("One", True), ("Two", False))
    )

    assert problems


def test_with_no_plan_a_lone_tests_commit_is_refused_as_before(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "A", "a")
    commit_feat(repo, "A", "a")
    commit_tests(repo, "Drive", "drive")

    problems = check_structure(repo, "main", paired=True)

    assert any("test: Drive" in problem for problem in problems), problems


def test_a_tests_commit_titled_for_another_group_is_not_the_test_only_groups(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "B", "b")
    commit_feat(repo, "B", "b")

    groups = plan(("Drive", True), ("B", False))

    assert check_structure(repo, "main", paired=True, groups=groups) == []
    assert commits_of_test_only_groups(repo, "main", groups) == set()
