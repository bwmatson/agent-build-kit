"""The push gate's red check runs the tests a tests commit added or changed, by id
(spec: red-check-by-id).

Over real git repositories and a real pytest: the Python profile's report reading judges
the run, and only its command is changed to use this interpreter instead of `uv`.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.red_check import passed_problem, wrap_report_command
from agent_build_kit.profiles.python_uv import PROFILE as PYTHON
from tests.factories import commit_files, git, init_repo
from tests.stub_gate_support import judged

OLD = "def test_old():\n    assert True\n"
NEW_FAILING = "\n\ndef test_new():\n    assert False\n"


class IdProfile:
    """The Python profile with a red command that runs this interpreter's pytest on the ids
    when given, else on the files, recording each (files, ids) it was asked for."""

    def __init__(self) -> None:
        self.asked: list[tuple[list[str], list[str] | None]] = []

    def clean_command(self, *, types: bool = False) -> str:
        return "exit 0"

    def red_command(self, files: list[str], ids: list[str] | None = None) -> str:
        self.asked.append((files, ids))
        targets = shlex.join(ids or files)
        run = f"{shlex.quote(sys.executable)} -m pytest {targets} -p no:cacheprovider --tb=line -q"
        return wrap_report_command(run, "--junitxml")

    def __getattr__(self, name: str) -> Any:
        return getattr(PYTHON, name)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """`main` holds a test file with one passing test; the unit branch is cut from it."""
    work = init_repo(tmp_path / "repo")
    commit_files(work, "base", {"README.md": "base\n", "tests/test_subject.py": OLD})
    git(work, "checkout", "-q", "-b", "spec/change/1-unit")
    return work


def tests_commit(repo: Path, files: dict[str, str]) -> None:
    commit_files(repo, "test: the cases", files)
    commit_files(repo, "feat: the code", {"src/subject.py": "x = 1\n"})


def test_a_new_failing_test_beside_passing_ones_is_accepted_and_only_it_is_run(repo: Path) -> None:
    tests_commit(repo, {"tests/test_subject.py": OLD + NEW_FAILING})
    profile = IdProfile()

    problems = judged(repo, profile)  # type: ignore[arg-type]

    assert problems == []
    assert profile.asked == [(["tests/test_subject.py"], ["tests/test_subject.py::test_new"])]


def test_a_new_test_that_passes_is_rejected_and_the_untouched_neighbour_is_not_counted(
    repo: Path,
) -> None:
    tests_commit(repo, {"tests/test_subject.py": OLD + "\n\ndef test_new():\n    assert True\n"})

    problems = judged(repo, IdProfile())  # type: ignore[arg-type]

    assert any(passed_problem(1) in problem for problem in problems), problems


def test_a_changed_existing_test_that_passes_is_rejected(repo: Path) -> None:
    changed = "def test_old():\n    x = 1\n    assert x == 1\n"
    tests_commit(repo, {"tests/test_subject.py": changed + NEW_FAILING})
    profile = IdProfile()

    problems = judged(repo, profile)  # type: ignore[arg-type]

    assert profile.asked[0][1] == [
        "tests/test_subject.py::test_new",
        "tests/test_subject.py::test_old",
    ]
    assert any(passed_problem(1) in problem for problem in problems), problems


def test_a_new_file_runs_all_of_its_tests(repo: Path) -> None:
    fresh = "def test_one():\n    assert False\n\n\ndef test_two():\n    assert False\n"
    tests_commit(repo, {"tests/test_fresh.py": fresh})
    profile = IdProfile()

    problems = judged(repo, profile)  # type: ignore[arg-type]

    assert problems == []
    assert profile.asked == [
        (
            ["tests/test_fresh.py"],
            ["tests/test_fresh.py::test_one", "tests/test_fresh.py::test_two"],
        )
    ]


def test_a_commit_with_no_test_to_select_runs_the_whole_files(repo: Path) -> None:
    commit_files(repo, "test: a case", {"tests/test_subject.py": OLD + NEW_FAILING})
    commit_files(repo, "feat: the code", {"src/subject.py": "x = 1\n"})
    commit_files(repo, "test: support", {"tests/support.py": "VALUE = 1\n"})
    commit_files(repo, "feat: more code", {"src/more.py": "y = 1\n"})
    profile = IdProfile()

    judged(repo, profile)  # type: ignore[arg-type]

    assert profile.asked == [
        (["tests/test_subject.py"], ["tests/test_subject.py::test_new"]),
        (["tests/support.py"], None),
    ]


def test_a_selection_that_collects_nothing_is_not_red(repo: Path) -> None:
    conftest = (
        "def pytest_collection_modifyitems(items, config):\n"
        "    config.hook.pytest_deselected(items=list(items))\n"
        "    items[:] = []\n"
    )
    tests_commit(repo, {"tests/conftest.py": conftest, "tests/test_subject.py": OLD + NEW_FAILING})
    profile = IdProfile()

    problems = judged(repo, profile)  # type: ignore[arg-type]

    assert profile.asked[0][1] == ["tests/test_subject.py::test_new"]
    assert any("nothing" in problem or "no tests" in problem for problem in problems), problems
