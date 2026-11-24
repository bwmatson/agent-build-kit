"""The tests-first gate asks the project a file belongs to (spec: node-npm-red-and-stubs).

Real branches in a real worktree, as in `test_gate.py`; the two toolchains are fake profiles
that take `is_test_path` from the real profile of their language and script the commands, so
each command's directory, files and verdict are what the gate is seen to ask of them.
"""

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import ProjectConfig
from agent_build_kit.pipeline.gate import check_branch, red_problems
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

    def __init__(
        self,
        name: str,
        home: str,
        *,
        red_ok: bool = True,
        reason: str = "red rejected",
        empty: bool = False,
    ) -> None:
        self.real = profiles.get(name)
        self.home = home
        self.red_ok = red_ok
        self.reason = reason
        self.empty = empty
        self.red_files: list[list[str]] = []
        self.red_outputs: list[str] = []

    def clean_command(self) -> str:
        return f'test "$(basename "$PWD")" = {self.home}'

    def red_command(self, files: list[str], ids: list[str] | None = None, **_: object) -> str:
        self.red_files.append(files)
        return 'printf "ran in %s" "$(basename "$PWD")"; exit 1'

    def interpret_red(self, output: str, exit_code: int) -> tuple[bool, list[str]]:
        self.red_outputs.append(output)
        return self.red_ok, [] if self.red_ok else [f"{self.home} {self.reason}"]

    def __getattr__(self, name):
        if name == "collected_nothing":
            raise AttributeError(name)  # a toolchain with no answer for an empty run
        return getattr(self.real, name)


class EmptyRunToolchain(Toolchain):
    """A toolchain that says whether its red run collected no test: `empty` says it did."""

    def collected_nothing(self, output: str, exit_code: int) -> bool:
        return self.empty


@pytest.fixture
def toolchains(monkeypatch: pytest.MonkeyPatch):
    """Both profiles scripted; the keywords say which red run is accepted, which collected no
    test (`python_empty`, rejected as it is) and whether the Python one can say so."""
    real = profiles.get

    def install(
        *,
        python_ok: bool = True,
        node_ok: bool = True,
        node_reason: str = "red rejected",
        python_empty: bool = False,
        python_reports: bool = True,
    ) -> dict[str, Toolchain]:
        python = EmptyRunToolchain if python_reports else Toolchain
        made = {
            "python-uv": python(
                "python-uv",
                "tree",
                red_ok=python_ok and not python_empty,
                reason="nothing collected" if python_empty else "red rejected",
                empty=python_empty,
            ),
            "node-npm": Toolchain("node-npm", "web", red_ok=node_ok, reason=node_reason),
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


def test_a_node_projects_tests_commit_with_a_source_that_has_a_body_fails_the_stub_check(
    repo: Path, toolchains
) -> None:
    made = toolchains()
    commit(
        repo,
        "test: covers it",
        {NODE_TEST: "// a test\n", "web/src/a.ts": "export function a() { return 1 }\n"},
    )
    commit(repo, "feat: implements it", {"web/src/b.ts": "export const x = 1\n"})

    problems = check_branch(repo, "main", profile=made["python-uv"], projects=PROJECTS)

    assert any("web/src/a.ts: a() has a body" in problem for problem in problems), problems
    assert made["node-npm"].red_files == [], "the shape is wrong, so nothing ran"


def test_a_node_projects_tests_commit_with_only_the_sentinel_body_passes_the_stub_check(
    repo: Path, toolchains
) -> None:
    made = toolchains()
    stub = "export function a() { throw new Error('not implemented') }\n"
    commit(repo, "test: covers it", {NODE_TEST: "// a test\n", "web/src/a.ts": stub})
    commit(repo, "feat: implements it", {"web/src/a.ts": "export function a() { return 1 }\n"})

    problems = check_branch(repo, "main", profile=made["python-uv"], projects=PROJECTS)

    assert problems == []


PYTHON_HELPER = "tests/support/graph_run.py"


def _tests_commit(repo: Path, files: dict[str, str]) -> None:
    """A tests commit of `files`, and the commit that implements it."""
    commit(repo, "test: covers it", files)
    commit(repo, "feat: implements it", {"src/thing.py": "x = 1\n"})


def _red_check(repo: Path, made: dict, log: list[str]) -> list[str]:
    """The problems of the build's red check, which logs the excuses it makes."""
    return red_problems(
        repo,
        git(repo, "rev-parse", "HEAD~1"),
        profile=made["python-uv"],
        projects=PROJECTS,
        log=log.append,
    )


def _push_gate(repo: Path, made: dict, log: list[str]) -> list[str]:
    """The problems of the push gate, which logs the excuses it makes."""
    return check_branch(repo, "main", profile=made["python-uv"], projects=PROJECTS, log=log.append)


CHECKS = [pytest.param(_red_check, id="red-check"), pytest.param(_push_gate, id="push-gate")]


@pytest.mark.parametrize("check", CHECKS)
def test_a_project_that_collected_no_test_is_excused_and_named_beside_a_project_that_failed(
    repo: Path, toolchains, check
) -> None:
    made = toolchains(python_empty=True)
    _tests_commit(repo, {NODE_TEST: "// a test\n", PYTHON_HELPER: "x = 1\n"})
    log: list[str] = []

    problems = check(repo, made, log)

    assert problems == []
    assert made["python-uv"].red_files == [[PYTHON_HELPER]], "both projects are run"
    assert made["node-npm"].red_files == [["src/widget.test.tsx"]]
    sha = git(repo, "rev-parse", "--short=8", "HEAD~1")
    assert [line for line in log if "excused" in line] == [
        f"{sha}: .: excused, its red run collected no test; web failed for the right reason"
    ]


@pytest.mark.parametrize("check", CHECKS)
@pytest.mark.parametrize("reason", ["nothing failed at the tests commit", "ImportError: no x"])
def test_a_project_that_collected_tests_and_failed_wrongly_is_rejected_beside_a_helper(
    repo: Path, toolchains, check, reason: str
) -> None:
    made = toolchains(python_empty=True, node_ok=False, node_reason=reason)
    _tests_commit(repo, {NODE_TEST: "// a test\n", PYTHON_HELPER: "x = 1\n"})
    log: list[str] = []

    problems = check(repo, made, log)

    assert [p.split(": ", 1)[1] for p in problems] == [
        "tree nothing collected",
        f"web: web {reason}",
    ], "no project failed for the right reason, so no excuse and every problem stands"
    assert not [line for line in log if "excused" in line]


@pytest.mark.parametrize("check", CHECKS)
def test_a_commit_whose_only_change_in_every_project_is_a_helper_is_rejected_with_no_excuse(
    repo: Path, toolchains, check
) -> None:
    made = toolchains(python_empty=True, node_ok=False, node_reason="nothing collected")
    _tests_commit(repo, {PYTHON_HELPER: "x = 1\n", "web/src/__tests__/support.ts": "1\n"})
    log: list[str] = []

    problems = check(repo, made, log)

    assert len(problems) == 1, "the node helper is not run, so only the python run is judged"
    assert "tree nothing collected" in problems[0]
    assert not [line for line in log if "excused" in line]


@pytest.mark.parametrize("check", CHECKS)
def test_a_commit_in_one_project_that_edits_only_a_helper_is_rejected_with_no_excuse(
    repo: Path, toolchains, check
) -> None:
    made = toolchains(python_empty=True)
    _tests_commit(repo, {PYTHON_HELPER: "x = 1\n"})
    log: list[str] = []

    problems = check(repo, made, log)

    assert len(problems) == 1
    assert made["python-uv"].red_files == [[PYTHON_HELPER]]
    assert made["node-npm"].red_files == []
    assert not [line for line in log if "excused" in line]


@pytest.mark.parametrize("check", CHECKS)
def test_a_project_whose_toolchain_cannot_say_a_run_collected_nothing_is_never_excused(
    repo: Path, toolchains, check
) -> None:
    made = toolchains(python_empty=True, python_reports=False)
    _tests_commit(repo, {NODE_TEST: "// a test\n", PYTHON_HELPER: "x = 1\n"})
    log: list[str] = []

    problems = check(repo, made, log)

    assert len(problems) == 1
    assert "tree nothing collected" in problems[0]
    assert not [line for line in log if "excused" in line]
