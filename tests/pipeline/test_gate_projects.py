"""The tests-first gate asks the project a file belongs to (spec: node-npm-red-and-stubs).

Real branches in a real worktree, as in `test_gate.py`; the two toolchains are fake profiles
that take `is_test_path` from the real profile of their language and script the commands, so
each command's directory, files and verdict are what the gate is seen to ask of them.
"""

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.gate import check_branch
from tests.factories import commit_files as commit
from tests.factories import git, init_repo

PYTHON_TEST = "tests/test_thing.py"
NODE_TEST = "web/src/widget.test.tsx"
PROJECTS = [
    ProjectConfig(path=".", profile="python-uv"),
    ProjectConfig(path="web", profile="node-npm"),
]


class Toolchain:
    """A profile whose commands run in the directory they are asked in and say so: the clean
    command fails outside `home`, the red command prints where it ran. What the gate asked is
    kept in `red_files` and `red_outputs`."""

    def __init__(self, name: str, home: str, *, red_ok: bool = True) -> None:
        self.real = profiles.get(name)
        self.home = home
        self.red_ok = red_ok
        self.red_files: list[list[str]] = []
        self.red_outputs: list[str] = []

    def clean_command(self) -> str:
        return f'test "$(basename "$PWD")" = {self.home}'

    def red_command(self, files: list[str]) -> str:
        self.red_files.append(files)
        return 'printf "ran in %s" "$(basename "$PWD")"; exit 1'

    def interpret_red(self, output: str, exit_code: int) -> tuple[bool, list[str]]:
        self.red_outputs.append(output)
        return self.red_ok, [] if self.red_ok else [f"{self.home} red rejected"]

    def __getattr__(self, name):
        return getattr(self.real, name)


@pytest.fixture
def toolchains(monkeypatch: pytest.MonkeyPatch):
    """Both profiles scripted; the keywords say which red run is accepted."""
    real = profiles.get

    def install(*, python_ok: bool = True, node_ok: bool = True) -> dict[str, Toolchain]:
        made = {
            "python-uv": Toolchain("python-uv", "tree", red_ok=python_ok),
            "node-npm": Toolchain("node-npm", "web", red_ok=node_ok),
        }
        monkeypatch.setattr(profiles, "get", lambda name: made.get(name) or real(name))
        return made

    return install


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    (work / "README.md").write_text("base\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    git(work, "checkout", "-q", "-b", "spec/change/1-unit")
    return work


def test_a_node_test_runs_the_node_red_command_in_its_project_and_no_pytest(
    repo: Path, toolchains
) -> None:
    made = toolchains()
    commit(repo, "test: covers it", {NODE_TEST: "// a test\n"})
    commit(repo, "feat: implements it", {"web/src/widget.ts": "export const x = 1\n"})

    problems = check_branch(repo, "main", profile=made["python-uv"], projects=PROJECTS)

    assert problems == [], "the clean command ran in the project directory too"
    assert made["node-npm"].red_files == [["src/widget.test.tsx"]], "paths in the project"
    assert [out.strip() for out in made["node-npm"].red_outputs] == ["ran in web"]
    assert made["python-uv"].red_files == []


@pytest.mark.parametrize("rejected", ["python-uv", "node-npm"])
def test_a_change_across_two_projects_fails_when_either_projects_check_fails(
    repo: Path, toolchains, rejected: str
) -> None:
    made = toolchains(python_ok=rejected != "python-uv", node_ok=rejected != "node-npm")
    commit(repo, "test: covers both", {PYTHON_TEST: "def test_x(): ...\n", NODE_TEST: "// t\n"})
    commit(repo, "feat: implements both", {"src/thing.py": "x = 1\n", "web/src/w.ts": "1\n"})

    problems = check_branch(repo, "main", profile=made["python-uv"], projects=PROJECTS)

    assert len(problems) == 1
    assert "red rejected" in problems[0]
    if rejected == "node-npm":
        assert problems[0].startswith(f"{git(repo, 'rev-parse', '--short=8', 'HEAD~1')}: web: ")
    assert made["python-uv"].red_files == [[PYTHON_TEST]]
    assert made["node-npm"].red_files == [["src/widget.test.tsx"]]


def test_a_repo_without_projects_takes_every_command_and_the_test_paths_from_its_profile(
    repo: Path, toolchains
) -> None:
    """The repo's profile is a node one: its test paths, not the generic ones, say which of
    the commit's files are tests."""
    made = toolchains()
    node = made["node-npm"]
    node.home = "tree"
    commit(repo, "test: covers it", {"src/widget.test.tsx": "// a test\n"})
    commit(repo, "feat: implements it", {"src/widget.ts": "export const x = 1\n"})

    problems = check_branch(repo, "main", profile=node)

    assert problems == []
    assert node.red_files == [["src/widget.test.tsx"]]
    assert made["python-uv"].red_files == []
