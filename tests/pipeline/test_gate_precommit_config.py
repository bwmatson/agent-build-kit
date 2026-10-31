"""The push gate's clean command at the tests commit carries the pre-commit configuration found
in the tree at that commit (spec: shared-quality-gate).

A real branch in a real worktree. The profile is python-uv with a clean command that prints the
line it runs and fails, so the gate's problem text shows the command that ran.
"""

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.gate import check_branch
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.factories import commit_files as commit
from tests.factories import git, init_repo

CONFIG = ".pre-commit-config.yaml"
ONE = ProjectConfig(path="one", profile="python-uv")


class Printing(PythonUvProfile):
    """Its clean command is the real one's shape, printed and failed instead of run."""

    def clean_command(self, *, types: bool = False) -> str:
        return "echo ran: pre-commit run --all-files; exit 1"

    def red_command(self, files: list[str], ids: list[str] | None = None) -> str:
        return "exit 1"

    def interpret_red(self, output: str, exit_code: int, *, stubbed: bool = False):
        return True, []


@pytest.fixture
def printing(monkeypatch: pytest.MonkeyPatch) -> Printing:
    made = Printing()
    monkeypatch.setattr(profiles, "get", lambda name: made)
    return made


def branch(tmp_path: Path, *, root_config: bool) -> Path:
    work = init_repo(tmp_path / "repo")
    commit(
        work, "base", {"README.md": "base\n", **({CONFIG: "repos: []\n"} if root_config else {})}
    )
    git(work, "checkout", "-q", "-b", "spec/change/1-unit")
    commit(work, "test: covers it", {"one/tests/test_x.py": "def test_x(): ...\n"})
    commit(work, "feat: implements it", {"one/src/x.py": "x = 1\n"})
    return work


def test_the_clean_command_names_the_root_configuration_found_in_the_tree(
    tmp_path: Path, printing: Printing
) -> None:
    work = branch(tmp_path, root_config=True)

    problems = check_branch(work, "main", profile=printing, projects=[ONE])

    assert len(problems) == 1, problems
    assert f"ran: pre-commit run --config ../{CONFIG} --all-files" in problems[0]


def test_with_no_configuration_anywhere_the_clean_command_is_unchanged(
    tmp_path: Path, printing: Printing
) -> None:
    work = branch(tmp_path, root_config=False)

    problems = check_branch(work, "main", profile=printing, projects=[ONE])

    assert len(problems) == 1, problems
    assert "ran: pre-commit run --all-files" in problems[0]
    assert "--config" not in problems[0]
