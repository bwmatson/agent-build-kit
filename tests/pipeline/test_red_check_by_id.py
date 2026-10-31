"""The push gate's red check runs the tests a tests commit added or changed, by id
(spec: red-check-by-id).

Over real git repositories and a real pytest: the Python profile's report reading judges
the run, and only its command is changed to use this interpreter instead of `uv`. The test
files each commit holds are the `.txt` files under `tests/child_modules/red_check_by_id/`,
kept as text so the suite's own selection of tests by id never takes them for tests.
"""

from __future__ import annotations

import shlex
import sys
from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.gate import check_branch
from agent_build_kit.pipeline.red_check import passed_problem, wrap_report_command
from agent_build_kit.profiles.python_uv import PROFILE as PYTHON
from tests.factories import commit_files, git, init_repo
from tests.stub_gate_support import ModeProfile, judged

SOURCES = Path(__file__).resolve().parent.parent / "child_modules" / "red_check_by_id"
SUBJECT = "tests/test_subject.py"
NEW = f"{SUBJECT}::test_new"


def source(name: str) -> str:
    return (SOURCES / f"{name}.txt").read_text()


class IdProfile(ModeProfile):
    """The Python profile with a red command that runs this interpreter's pytest on the ids
    when given, else on the files, recording each (files, ids) it was asked for, and the
    Python profile's own reading of the report."""

    def __init__(self) -> None:
        super().__init__()
        self.asked: list[tuple[list[str], list[str] | None]] = []

    def interpret_red(
        self, output: str, exit_code: int, *, stubbed: bool = False
    ) -> tuple[bool, list[str]]:
        return PYTHON.interpret_red(output, exit_code, stubbed=stubbed)

    def red_command(self, files: list[str], ids: list[str] | None = None) -> str:
        self.asked.append((files, ids))
        targets = shlex.join(ids or files)
        run = f"{shlex.quote(sys.executable)} -m pytest {targets} -p no:cacheprovider --tb=line -q"
        return wrap_report_command(run, "--junitxml")


def branch_with(tmp_path: Path, base_files: dict[str, str]) -> Path:
    """`main` holds `base_files`; the unit branch is cut from it."""
    work = init_repo(tmp_path / "repo")
    commit_files(work, "base", {"README.md": "base\n", **base_files})
    git(work, "checkout", "-q", "-b", "spec/change/1-unit")
    return work


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return branch_with(tmp_path, {SUBJECT: source("old_case")})


def commit_cases(repo: Path, files: dict[str, str]) -> None:
    commit_files(repo, "test: the cases", files)
    commit_files(repo, "feat: the code", {"src/subject.py": "x = 1\n"})


def test_a_new_failing_test_beside_passing_ones_is_accepted_and_only_it_is_run(repo: Path) -> None:
    commit_cases(repo, {SUBJECT: source("new_failing_case")})
    profile = IdProfile()

    problems = judged(repo, profile)

    assert problems == []
    assert profile.asked == [([SUBJECT], [NEW])]


def test_a_new_test_that_passes_is_rejected_and_the_untouched_neighbour_is_not_counted(
    repo: Path,
) -> None:
    commit_cases(repo, {SUBJECT: source("new_passing_case")})

    problems = judged(repo, IdProfile())

    assert any(passed_problem(1) in problem for problem in problems), problems


def test_a_changed_existing_test_that_passes_is_rejected(repo: Path) -> None:
    commit_cases(repo, {SUBJECT: source("changed_old_case")})
    profile = IdProfile()

    problems = judged(repo, profile)

    assert profile.asked[0][1] == [NEW, f"{SUBJECT}::test_old"]
    assert any(passed_problem(1) in problem for problem in problems), problems


def test_a_new_file_runs_all_of_its_tests(repo: Path) -> None:
    commit_cases(repo, {"tests/test_fresh.py": source("fresh_file")})
    profile = IdProfile()

    problems = judged(repo, profile)

    assert problems == []
    assert profile.asked == [
        (
            ["tests/test_fresh.py"],
            ["tests/test_fresh.py::test_one", "tests/test_fresh.py::test_two"],
        )
    ]


def test_a_commit_with_no_test_to_select_runs_the_whole_files(repo: Path) -> None:
    commit_cases(repo, {SUBJECT: source("new_failing_case")})
    commit_files(repo, "test: support", {"tests/support.py": source("support_module")})
    commit_files(repo, "feat: more code", {"src/more.py": "y = 1\n"})
    profile = IdProfile()

    judged(repo, profile)

    assert profile.asked == [([SUBJECT], [NEW]), (["tests/support.py"], None)]


def test_a_selection_that_collects_nothing_is_not_red(repo: Path) -> None:
    commit_cases(
        repo,
        {
            "tests/conftest.py": source("collect_nothing_conftest"),
            SUBJECT: source("new_failing_case"),
        },
    )
    profile = IdProfile()

    problems = judged(repo, profile)

    assert profile.asked[0][1] == ["tests/conftest.py", NEW]
    assert any("nothing" in problem or "no tests" in problem for problem in problems), problems


def test_a_failing_test_on_a_base_class_the_runner_does_not_collect_is_accepted(
    repo: Path,
) -> None:
    commit_cases(repo, {"tests/test_base.py": source("base_class_cases")})
    profile = IdProfile()

    problems = judged(repo, profile)

    assert problems == []
    assert profile.asked == [(["tests/test_base.py"], None)]


def test_a_fixture_named_like_a_test_is_not_selected(repo: Path) -> None:
    commit_cases(repo, {SUBJECT: source("fixture_named_test")})
    profile = IdProfile()

    problems = judged(repo, profile)

    assert problems == []
    assert profile.asked == [([SUBJECT], [NEW])]


def test_a_function_inside_a_new_test_is_not_selected(repo: Path) -> None:
    commit_cases(repo, {SUBJECT: source("nested_in_test")})
    profile = IdProfile()

    problems = judged(repo, profile)

    assert problems == []
    assert profile.asked == [([SUBJECT], [NEW])]


def test_a_project_in_a_subdirectory_is_asked_for_ids_relative_to_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work = branch_with(tmp_path, {f"services/app/{SUBJECT}": source("old_case")})
    commit_cases(work, {f"services/app/{SUBJECT}": source("new_failing_case")})
    profile = IdProfile()
    real = profiles.get
    monkeypatch.setattr(
        profiles, "get", lambda name: profile if name == "python-uv" else real(name)
    )

    problems = check_branch(work, "main", projects=[ProjectConfig(path="services/app")])

    assert problems == []
    assert profile.asked == [([SUBJECT], [NEW])]
