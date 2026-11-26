"""The red check and the push gate give the runner only files the toolchain can run
(spec: red-check-runs-runnable-test-files).

Real git repositories; the runner is replaced by a recording of the arguments the toolchain's
own red command was asked to build, and the run itself exits red.
"""

import shlex
from pathlib import Path
from typing import Any, cast

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import ProjectConfig
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

    def red_command(
        self, files: list[str], ids: list[str] | None = None, *, project: Path | None = None
    ) -> str:
        self.files.append(files)
        self.commands.append(self.real.red_command(files, ids, project=project))
        return "exit 1"

    def clean_command(self, *, types: bool = False) -> str:
        return "true"

    def interpret_red(
        self, output: str, exit_code: int, *, stubbed: bool = False, rules: object = None
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


def test_a_deleted_test_file_is_not_named_in_the_narrowed_run_or_the_run_of_the_files_whole(
    repo: Path,
) -> None:
    git(repo, "rm", "-q", "tests/test_old.py")
    commit(repo, "test: moves one", {"tests/test_new.py": FAILING})
    profile = Recording(PYTHON)

    red_problems(repo, git(repo, "rev-parse", "HEAD"), profile=profile.toolchain)

    (command,) = profile.commands
    assert "test_old" not in command, "neither run names the deleted file"
    words = shlex.split(command)
    assert "tests/test_new.py::test_new" in words, "the narrowed run"
    assert "tests/test_new.py" in words, "the run of the files whole"
    assert profile.files == [["tests/test_new.py"]]


def test_the_push_gate_does_not_give_the_runner_a_deleted_test_file(repo: Path) -> None:
    git(repo, "rm", "-q", "tests/test_old.py")
    commit(repo, "test: moves one", {"tests/test_new.py": FAILING})
    commit(repo, "feat: implements it", {"src/new.py": "x = 1\n"})
    profile = Recording(PYTHON)

    problems = check_branch(repo, "main", profile=profile.toolchain)

    assert problems == []
    assert profile.files == [["tests/test_new.py"]]


NODE_FAILING = "test('x', () => { throw new Error('no') })\n"
WEB = [ProjectConfig(path="web", profile="node-npm")]


@pytest.fixture
def web_repo(repo: Path) -> Path:
    """`repo` with a node project's test file, `web/src/old.test.ts`, already on main."""
    git(repo, "checkout", "-q", "main")
    commit(repo, "web", {"web/src/old.test.ts": NODE_FAILING})
    git(repo, "checkout", "-q", "spec/change/1-unit")
    git(repo, "rebase", "-q", "main")
    return repo


def test_a_deleted_test_file_of_a_project_below_the_root_is_left_out_of_the_red_run(
    web_repo: Path,
) -> None:
    git(web_repo, "rm", "-q", "web/src/old.test.ts")
    commit(web_repo, "test: moves one", {"web/src/new.test.ts": NODE_FAILING})
    profile = Recording(NODE)

    with profiles.registered(profile.toolchain):
        red_problems(web_repo, git(web_repo, "rev-parse", "HEAD"), profile=PYTHON, projects=WEB)

    assert profile.files == [["src/new.test.ts"]]


def test_the_push_gate_leaves_a_deleted_test_file_of_a_project_below_the_root_out(
    web_repo: Path,
) -> None:
    git(web_repo, "rm", "-q", "web/src/old.test.ts")
    commit(web_repo, "test: moves one", {"web/src/new.test.ts": NODE_FAILING})
    commit(web_repo, "feat: implements it", {"web/src/widget.ts": "export const x = 1\n"})
    profile = Recording(NODE)

    with profiles.registered(profile.toolchain):
        problems = check_branch(web_repo, "main", profile=PYTHON, projects=WEB)

    assert problems == []
    assert profile.files == [["src/new.test.ts"]]


def test_a_renamed_test_file_runs_under_its_new_path_only(repo: Path) -> None:
    git(repo, "mv", "tests/test_old.py", "tests/test_renamed.py")
    commit(repo, "test: renames one", {"tests/test_renamed.py": FAILING})
    profile = Recording(PYTHON)

    red_problems(repo, git(repo, "rev-parse", "HEAD"), profile=profile.toolchain)

    assert profile.files == [["tests/test_renamed.py"]]
    assert "test_old" not in profile.commands[0]


def test_a_tests_commit_that_only_deletes_a_test_file_is_a_tests_commit_with_no_red_command(
    repo: Path,
) -> None:
    git(repo, "rm", "-q", "tests/test_old.py")
    commit(repo, "test: removes one", {})
    commit(repo, "feat: code", {"src/thing.py": "x = 1\n"})
    profile = Recording(PYTHON)

    problems = check_branch(repo, "main", profile=profile.toolchain)

    assert problems == [], "the deletion counts as the tests commit that precedes the code"
    assert profile.commands == []
    assert red_problems(repo, git(repo, "rev-parse", "HEAD~1"), profile=profile.toolchain) == []
    assert profile.commands == []


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


class Preparing(Recording):
    """A recording profile that is asked to prepare the worktree the red command runs in.

    Preparing leaves a marker file the red command reads, so the command's output shows
    whether the worktree was prepared before it ran."""

    def __init__(self, real: ToolchainProfile) -> None:
        super().__init__(real)
        self.prepared: list[tuple[Path, Path, str, bool]] = []
        self.outputs: list[str] = []

    def prepare_worktree(self, checkout: Path, worktree: Path, *, project: str = ".") -> None:
        has_tests = (worktree / "tests" / "test_new.py").is_file()
        self.prepared.append((checkout, worktree, project, has_tests))
        (worktree / "prepared.marker").write_text("yes\n")

    def red_command(
        self, files: list[str], ids: list[str] | None = None, *, project: Path | None = None
    ) -> str:
        super().red_command(files, ids, project=project)
        return "cat prepared.marker; exit 1"

    def interpret_red(
        self, output: str, exit_code: int, *, stubbed: bool = False, rules: object = None
    ) -> tuple[bool, list[str]]:
        self.outputs.append(output)
        return True, []


def test_the_red_check_prepares_the_worktree_it_runs_in_once_before_the_test_command(
    repo: Path,
) -> None:
    commit(repo, "test: adds one", {"tests/test_new.py": FAILING})
    profile = Preparing(PYTHON)

    red_problems(repo, git(repo, "rev-parse", "HEAD"), profile=profile.toolchain)

    assert len(profile.prepared) == 1, "prepared exactly once"
    checkout, worktree, project, has_tests = profile.prepared[0]
    assert checkout == repo
    assert worktree != repo
    assert project == "."
    assert has_tests, "prepared after the tests commit was checked out"
    assert profile.outputs == ["yes\n"], "the marker existed when the command ran"


class Observing(Recording):
    """A recording profile whose red command reports whether the tree holds a marker, and
    which records what it was told the run printed and exited with."""

    def __init__(self, real: ToolchainProfile) -> None:
        super().__init__(real)
        self.runs: list[tuple[str, int]] = []

    def red_command(
        self, files: list[str], ids: list[str] | None = None, *, project: Path | None = None
    ) -> str:
        super().red_command(files, ids, project=project)
        return "if test -e prepared.marker; then echo marked; else echo untouched; fi; exit 1"

    def interpret_red(
        self, output: str, exit_code: int, *, stubbed: bool = False, rules: object = None
    ) -> tuple[bool, list[str]]:
        self.runs.append((output, exit_code))
        return True, []


def test_a_profile_without_prepare_worktree_runs_the_red_command_in_an_untouched_tree(
    repo: Path,
) -> None:
    assert not hasattr(PYTHON, "prepare_worktree"), "the premise: this profile prepares nothing"
    commit(repo, "test: adds one", {"tests/test_new.py": FAILING})
    profile = Observing(PYTHON)

    problems = red_problems(repo, git(repo, "rev-parse", "HEAD"), profile=profile.toolchain)

    assert problems == []
    assert profile.runs == [("untouched\n", 1)]


def test_the_push_gate_prepares_the_worktree_once_before_its_clean_and_red_commands(
    repo: Path,
) -> None:
    commit(repo, "test: adds one", {"tests/test_new.py": FAILING})
    commit(repo, "feat: implements it", {"src/new.py": "x = 1\n"})
    profile = Preparing(PYTHON)

    problems = check_branch(repo, "main", profile=profile.toolchain)

    assert problems == []
    assert len(profile.prepared) == 1, "prepared exactly once, for the clean and red commands"
    checkout, worktree, project, has_tests = profile.prepared[0]
    assert checkout == repo
    assert worktree != repo
    assert project == "."
    assert has_tests, "prepared after the tests commit was checked out"
    assert profile.outputs == ["yes\n"], "the marker existed when the red command ran"


class MemberAware(Recording):
    """A profile whose run of a project exits 2 with `Failed to spawn: pytest` unless the real
    red command it is given for that project differs from the project-less one (a member's
    command), in which case the run fails for the missing behaviour."""

    name = "member-aware"

    def red_command(
        self, files: list[str], ids: list[str] | None = None, *, project: Path | None = None
    ) -> str:
        super().red_command(files, ids, project=project)
        super().red_command(files, ids)
        built, plain = self.commands[-2:]
        if built != plain:
            return "echo 'FAILED tests/test_new.py::test_new - assert False'; exit 1"
        return "echo 'error: Failed to spawn: pytest' >&2; exit 2"

    def interpret_red(
        self, output: str, exit_code: int, *, stubbed: bool = False, rules: object = None
    ) -> tuple[bool, list[str]]:
        if exit_code == 1 and "Failed to spawn" not in output:
            return True, []
        return False, ["no tests ran, so nothing was shown to fail"]


MEMBER_TEST = "pkg/core/tests/test_new.py"


@pytest.mark.parametrize(
    ("already", "changed"),
    [
        pytest.param({}, FAILING, id="a-new-test-is-selected-by-id"),
        pytest.param(
            {MEMBER_TEST: FAILING},
            "X = 1\n" + FAILING,
            id="a-module-level-edit-runs-the-file-whole",
        ),
    ],
)
def test_the_red_check_over_a_workspace_members_new_test_is_judged_on_the_members_command(
    repo: Path, already: dict[str, str], changed: str
) -> None:
    commit(
        repo,
        "workspace",
        {
            "pyproject.toml": '[project]\nname = "r"\nversion = "0"\n'
            '[tool.uv.workspace]\nmembers = ["pkg/core"]\n',
            "uv.lock": "version = 1\n",
            "pkg/core/pyproject.toml": '[project]\nname = "core"\nversion = "0"\n',
            **already,
        },
    )
    commit(repo, "test: changes one", {MEMBER_TEST: changed})
    profile = MemberAware(PYTHON)

    with profiles.registered(profile.toolchain):
        problems = red_problems(
            repo,
            git(repo, "rev-parse", "HEAD"),
            profile=profile.toolchain,
            projects=[ProjectConfig(path="pkg/core", profile="member-aware")],
        )

    assert problems == []
