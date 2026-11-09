"""The red check and the push gate give the runner only files the toolchain can run
(spec: red-check-runs-runnable-test-files).

Real git repositories; the runner is replaced by a recording of the arguments the toolchain's
own red command was asked to build, and the run itself exits red.
"""

import shlex
from pathlib import Path
from typing import Any, cast

import pytest

from agent_build_kit.pipeline.gate import check_branch, red_problems
from agent_build_kit.profiles.base import ToolchainProfile
from agent_build_kit.profiles.node_npm import PROFILE as NODE
from agent_build_kit.profiles.python_uv import PROFILE as PYTHON
from tests.factories import commit_files as commit
from tests.factories import git, init_repo

SNAPSHOT = "tests/snapshots/default_tools.json"
FAILING = "def test_new():\n    assert False\n"


class Recording:
    """A profile whose red command is the real one, recorded, and whose run exits red."""

    def __init__(self, real: ToolchainProfile) -> None:
        self.real = real
        self.commands: list[str] = []
        self.files: list[list[str]] = []

    @property
    def toolchain(self) -> ToolchainProfile:
        return cast(ToolchainProfile, self)

    def red_command(self, files: list[str], ids: list[str] | None = None) -> str:
        self.files.append(files)
        self.commands.append(self.real.red_command(files, ids))
        return "exit 1"

    def clean_command(self, *, types: bool = False) -> str:
        return "true"

    def interpret_red(
        self, output: str, exit_code: int, *, stubbed: bool = False
    ) -> tuple[bool, list[str]]:
        return True, []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.real, name)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """The files the unit's commits change already exist on main, so none is a tests commit."""
    work = init_repo(tmp_path / "repo")
    commit(
        work,
        "base",
        {"README.md": "base\n", SNAPSHOT: '{"tools": []}\n', "tests/test_old.py": "x = 1\n"},
    )
    git(work, "checkout", "-q", "-b", "spec/change/1-unit")
    return work


def test_the_red_command_names_the_python_file_and_not_the_data_file_in_both_runs(
    repo: Path,
) -> None:
    commit(repo, "test: adds one", {"tests/test_new.py": FAILING, SNAPSHOT: '{"tools": [1]}\n'})
    profile = Recording(PYTHON)

    red_problems(repo, git(repo, "rev-parse", "HEAD"), profile=profile.toolchain)

    (command,) = profile.commands
    assert "default_tools.json" not in command
    words = shlex.split(command)
    assert "tests/test_new.py::test_new" in words, "the narrowed run"
    assert "tests/test_new.py" in words, "the run of the files whole"


def test_a_conftest_stays_among_the_runner_arguments(repo: Path) -> None:
    commit(
        repo,
        "test: adds one",
        {"tests/test_new.py": FAILING, "tests/conftest.py": "import pytest\n", SNAPSHOT: "{}\n"},
    )
    profile = Recording(PYTHON)

    red_problems(repo, git(repo, "rev-parse", "HEAD"), profile=profile.toolchain)

    assert sorted(profile.files[0]) == ["tests/conftest.py", "tests/test_new.py"]


def test_a_tests_commit_with_only_a_data_file_builds_no_red_command(repo: Path) -> None:
    commit(repo, "test: snapshot only", {SNAPSHOT: '{"tools": [3]}\n'})
    commit(repo, "feat: code", {"src/thing.py": "x = 1\n"})
    profile = Recording(PYTHON)

    problems = check_branch(repo, "main", profile=profile.toolchain)

    assert problems == []
    assert profile.commands == []
    assert red_problems(repo, git(repo, "rev-parse", "HEAD~1"), profile=profile.toolchain) == []


@pytest.mark.parametrize(
    ("path", "runnable"),
    [
        ("tests/test_a.py", True),
        ("tests/conftest.py", True),
        ("tests/support/helpers.py", True),
        ("tests/snapshots/default_tools.json", False),
        ("tests/data/fixture.txt", False),
    ],
)
def test_the_python_toolchain_runs_py_files_only(path: str, runnable: bool) -> None:
    assert PYTHON.runs_path(path) is runnable


@pytest.mark.parametrize(
    ("path", "runnable"),
    [
        ("src/a.test.ts", True),
        ("src/__tests__/a.test.ts", True),
        ("src/__tests__/a.ts", False),
        ("src/__tests__/data.json", False),
        ("src/__tests__/__snapshots__/a.test.ts.snap", False),
    ],
)
def test_the_node_toolchain_runs_only_files_vitest_reports_a_suite_for(
    path: str, runnable: bool
) -> None:
    assert NODE.runs_path(path) is runnable


def test_a_node_tests_commit_gives_the_runner_its_test_file_and_not_the_data_file(
    repo: Path,
) -> None:
    files = {
        "src/a.test.ts": "test('x', () => { throw new Error('no') })\n",
        "src/__tests__/data.json": "{}\n",
    }
    commit(repo, "test: node", files)
    profile = Recording(NODE)

    red_problems(repo, git(repo, "rev-parse", "HEAD"), profile=profile.toolchain)

    assert profile.files == [["src/a.test.ts"]]
