"""The commit-order check's paired mode: every `test:` commit is followed directly by a
`feat:` commit of the same title (spec: per-group-commits).

Over real git repositories in tmp_path, because the rules are about commits and diffs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.commit_order import check_structure
from tests.factories import commit_files as commit
from tests.factories import git, init_repo


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    init_repo(tmp_path)
    (tmp_path / "README.md").write_text("base\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-qm", "base")
    git(tmp_path, "checkout", "-q", "-b", "spec/change/1-unit")
    return tmp_path


def add_tests(repo: Path, title: str, name: str, content: str = "def test_x(): ...\n") -> None:
    commit(repo, f"test: {title}", {f"tests/test_{name}.py": content})


def add_feat(repo: Path, title: str, name: str) -> None:
    commit(repo, f"feat: {title}", {f"src/{name}.py": "x = 1\n"})


def test_two_correct_pairs_pass_the_paired_check(repo: Path) -> None:
    add_tests(repo, "one", "one")
    add_feat(repo, "one", "one")
    add_tests(repo, "two", "two")
    add_feat(repo, "two", "two")

    assert check_structure(repo, "main", paired=True) == []


def test_two_tests_commits_in_a_row_are_reported_naming_the_second(repo: Path) -> None:
    add_tests(repo, "one", "one")
    add_tests(repo, "two", "two")
    add_feat(repo, "two", "two")

    problems = check_structure(repo, "main", paired=True)

    assert any("test: two" in problem for problem in problems), problems
    assert not any("test: one" in problem for problem in problems), problems


def test_a_tests_commit_followed_by_another_title_is_reported_naming_both(repo: Path) -> None:
    add_tests(repo, "one", "one")
    add_feat(repo, "another", "one")

    problems = check_structure(repo, "main", paired=True)

    assert any("one" in problem and "another" in problem for problem in problems), problems
    assert check_structure(repo, "main") == []


def test_a_tests_commit_holding_logic_is_still_reported_as_today(repo: Path) -> None:
    commit(
        repo,
        "test: one",
        {
            "tests/test_one.py": "def test_x(): ...\n",
            "src/one.py": "def x() -> int:\n    return 1\n",
        },
    )
    add_feat(repo, "one", "other")

    paired = check_structure(repo, "main", paired=True)

    assert paired
    assert all(problem in paired for problem in check_structure(repo, "main"))


def test_an_unstubbed_branch_of_one_pair_passes_with_the_paired_check_on(repo: Path) -> None:
    add_tests(repo, "the unit", "unit")
    add_feat(repo, "the unit", "unit")

    assert check_structure(repo, "main", paired=True) == []
    assert check_structure(repo, "main") == []
