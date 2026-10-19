"""The commit-order check's paired mode: every `test:` commit is followed directly by a
`feat:` commit of the same title (spec: per-group-commits).

Over real git repositories in tmp_path, because the rules are about commits and diffs.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.commit_order import check_structure
from tests.factories import commit_files as commit
from tests.stub_gate_support import (
    commit_feat,
    commit_tests,
    repo,  # noqa: F401  (the fixture)
)


def test_two_correct_pairs_pass_the_paired_check(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "one", "one")
    commit_feat(repo, "one", "one")
    commit_tests(repo, "two", "two")
    commit_feat(repo, "two", "two")

    assert check_structure(repo, "main", paired=True) == []


def test_two_tests_commits_in_a_row_are_reported_naming_the_second(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "one", "one")
    commit_tests(repo, "two", "two")
    commit_feat(repo, "two", "two")

    problems = check_structure(repo, "main", paired=True)

    assert any("test: two" in problem for problem in problems), problems
    assert not any("test: one" in problem for problem in problems), problems


def test_a_tests_commit_followed_by_another_title_is_reported_naming_both(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "one", "one")
    commit_feat(repo, "another", "one")

    problems = check_structure(repo, "main", paired=True)

    assert any("one" in problem and "another" in problem for problem in problems), problems
    assert check_structure(repo, "main") == []


def test_a_tests_commit_holding_logic_is_still_reported_as_today(repo: Path) -> None:  # noqa: F811 — fixture
    commit(
        repo,
        "test: one",
        {
            "tests/test_one.py": "def test_x(): ...\n",
            "src/one.py": "def x() -> int:\n    return 1\n",
        },
    )
    commit_feat(repo, "one", "other")

    paired = check_structure(repo, "main", paired=True)

    assert paired
    assert all(problem in paired for problem in check_structure(repo, "main"))


def test_an_unstubbed_branch_of_one_pair_passes_with_the_paired_check_on(repo: Path) -> None:  # noqa: F811 — fixture
    commit_tests(repo, "the unit", "unit")
    commit_feat(repo, "the unit", "unit")

    assert check_structure(repo, "main", paired=True) == []
    assert check_structure(repo, "main") == []
