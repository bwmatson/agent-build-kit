"""The tier 1 runner's selected-then-full flow in a fix round (spec: affected-tests-in-fix-rounds).

The command runner is the faked boundary: it sees the argv and directory of every command
and answers with an exit status and output. The profile is a python-uv one whose commands
are named words, so the order of what ran reads as a list.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from agent_build_kit.config import AffectedConfig, ProjectConfig, RepoConfig
from agent_build_kit.pipeline.wiring import build_tier1
from agent_build_kit.profiles.python_uv import PythonUvProfile
from tests.conftest import make_installation

FAILED_OUTPUT = "FAILED tests/test_a.py::test_one - assert 1 == 2\nFAILED tests/test_b.py::test_two"
CHANGED = ["src/a b.py", "src/c.py"]
IDS = ["tests/test_a.py::test_one", "tests/test_b.py::test_two"]
TEMPLATE = "select --files {changed_files} --failed {failed_ids} -q"


class Profile(PythonUvProfile):
    """Lint, the full tests and the selected tests, each one named word."""

    def __init__(
        self, selected: list[list[str]] | None = None, lint: list[str] | None = None
    ) -> None:
        self.selected = selected
        self.lint = lint or ["lint"]
        self.asked: list[tuple[list[str], list[str]]] = []

    def lint_command(self, base: str) -> list[str]:
        return self.lint

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        return [["full-tests"]]

    def affected_test_commands(
        self, repo: Path, changed_files: list[str], failed_ids: list[str], *, seed: Path
    ) -> list[list[str]] | None:
        self.asked.append((changed_files, failed_ids))
        return self.selected

    def failed_tests(self, output: str) -> list[str]:
        return [line.split()[1] for line in output.splitlines() if line.startswith("FAILED ")]


class Commands:
    """The faked runner: what ran, in what directory, and how each word ends."""

    def __init__(self, **answers: tuple[int, str]) -> None:
        self.answers = answers
        self.ran: list[list[str]] = []
        self.directories: list[Path] = []

    def __call__(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        self.ran.append(command)
        self.directories.append(cwd)
        code, out = self.answers.get(command[0], (0, ""))
        return subprocess.CompletedProcess(command, code, out, "")

    def words(self) -> list[str]:
        return [command[0] for command in self.ran]


def repo_config(tmp_path: Path, mode: str = "profile", command: str | None = None) -> RepoConfig:
    return RepoConfig(
        path=tmp_path,
        changelog=None,
        checks={"affected": {"mode": mode, **({"command": command} if command else {})}},
    )


def fix_round(
    tmp_path: Path,
    commands: Commands,
    *,
    mode: str = "profile",
    command: str | None = None,
    profile: Profile | None = None,
    log: list[str] | None = None,
    projects: list[ProjectConfig] | None = None,
    failed_output: str = FAILED_OUTPUT,
    changed: list[str] = CHANGED,
) -> tuple[bool, str]:
    tier1 = build_tier1(
        run=commands,
        changed=lambda *a: changed,
        profile=profile or Profile([["selected"]]),
        repo=repo_config(tmp_path, mode, command),
        projects=projects,
        log=log.append if log is not None else None,
    )
    return tier1(cwd=tmp_path, base="main", failed_output=failed_output)


def test_the_mode_defaults_to_off_and_a_command_mode_needs_its_template() -> None:
    assert RepoConfig(path=Path("x")).checks.affected == AffectedConfig(mode="off", command=None)
    assert AffectedConfig(mode="command", command=TEMPLATE).command == TEMPLATE
    with pytest.raises(ValidationError, match="command"):
        AffectedConfig(mode="command")
    with pytest.raises(ValidationError, match="command"):
        RepoConfig.model_validate({"path": "x", "checks": {"affected": {"mode": "command"}}})


def test_off_runs_the_full_tests_even_in_a_fix_round(tmp_path: Path) -> None:
    commands = Commands()
    profile = Profile([["selected"]])

    passed, _ = fix_round(tmp_path, commands, mode="off", profile=profile)

    assert passed
    assert commands.words() == ["lint", "full-tests"]
    assert profile.asked == []


def test_a_profile_that_selects_nothing_runs_the_full_suite_and_says_why_once(
    tmp_path: Path,
) -> None:
    commands = Commands()
    log: list[str] = []

    passed, _ = fix_round(tmp_path, commands, profile=Profile(None), log=log)

    assert passed
    assert commands.words() == ["lint", "full-tests"]
    said = [line for line in log if "affected" in line.lower()]
    assert len(said) == 1 and "full" in said[0].lower(), log


def test_the_profile_is_asked_with_the_changed_files_and_the_failed_identifiers(
    tmp_path: Path,
) -> None:
    profile = Profile([["selected"]])

    fix_round(tmp_path, Commands(), profile=profile)

    assert profile.asked == [(CHANGED, IDS)]


def test_the_template_expands_each_placeholder_to_separate_arguments_in_the_project_directory(
    tmp_path: Path,
) -> None:
    commands = Commands()
    (tmp_path / "svc").mkdir()
    project = ProjectConfig(path="svc")

    # The files are relative to the project, as the profile's own commands take them.
    fix_round(
        tmp_path,
        commands,
        mode="command",
        command=TEMPLATE,
        projects=[project],
        changed=[f"svc/{name}" for name in CHANGED],
    )

    selected = [c for c in commands.ran if c[0] == "select"]
    assert selected == [["select", "--files", *CHANGED, "--failed", *IDS, "-q"]]
    assert commands.directories[commands.ran.index(selected[0])] == tmp_path / "svc"


def test_a_template_command_runs_under_the_tier_1_command_time_limit(tmp_path: Path) -> None:
    make_installation(tmp_path / "planning", limits=dict(tier1_command_seconds=2))
    hangs = "import time; print('selecting', flush=True); time.sleep(30)"
    template = shlex.join([sys.executable, "-c", hangs])
    tier1 = build_tier1(
        changed=lambda *a: CHANGED,
        profile=Profile(lint=[sys.executable, "-c", "pass"]),
        repo=repo_config(tmp_path, "command", template),
    )

    passed, message = tier1(cwd=tmp_path, base="main", failed_output=FAILED_OUTPUT)

    assert not passed
    assert "2 seconds" in message
    assert "selecting" in message


def test_a_failed_selected_run_goes_back_without_the_full_suite(tmp_path: Path) -> None:
    commands = Commands(selected=(1, "FAILED tests/test_a.py::test_one"))

    passed, output = fix_round(tmp_path, commands)

    assert not passed
    assert "test_one" in output
    assert commands.words() == ["lint", "selected"]


def test_a_failed_lint_goes_back_without_selecting_or_the_full_suite(tmp_path: Path) -> None:
    commands = Commands(lint=(1, "E501 line too long"))

    passed, output = fix_round(tmp_path, commands)

    assert not passed
    assert "E501" in output
    assert commands.words() == ["lint"]


def test_a_selected_pass_is_confirmed_by_one_full_run_which_is_the_green(tmp_path: Path) -> None:
    commands = Commands()

    passed, output = fix_round(tmp_path, commands)

    assert (passed, output) == (True, "")
    assert commands.words().count("selected") == 1
    assert commands.words().count("full-tests") == 1
    assert commands.words().index("lint") < commands.words().index("selected")
    assert commands.words().index("selected") < commands.words().index("full-tests")


def test_nothing_affected_still_ends_with_the_full_suite(tmp_path: Path) -> None:
    commands = Commands()

    passed, _ = fix_round(tmp_path, commands, profile=Profile([]))

    assert passed
    assert commands.words() == ["lint", "full-tests"]


def test_a_selected_pass_and_a_full_failure_is_a_disagreement_returned_with_the_full_output(
    tmp_path: Path,
) -> None:
    commands = Commands(**{"full-tests": (1, "1 test failed: test_three")})

    passed, output = fix_round(tmp_path, commands)

    assert not passed
    assert "test_three" in output
    assert commands.words() == ["lint", "selected", "full-tests"]


def test_a_template_that_cannot_start_runs_the_full_suite_and_records_why(
    tmp_path: Path,
) -> None:
    class NotFound(Commands):
        def __call__(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
            if command[0] == "select":
                self.ran.append(command)
                raise FileNotFoundError(command[0])
            return super().__call__(command, cwd=cwd)

    commands = NotFound()
    log: list[str] = []

    passed, _ = fix_round(tmp_path, commands, mode="command", command=TEMPLATE, log=log)

    assert passed
    assert commands.words() == ["lint", "select", "lint", "full-tests"]
    assert any("select" in line and "full" in line.lower() for line in log), log


@pytest.mark.parametrize("failed_output", ["", "   \n"])
def test_a_check_with_no_failure_to_answer_runs_in_full(tmp_path: Path, failed_output: str) -> None:
    commands = Commands()
    profile = Profile([["selected"]])

    passed, _ = fix_round(tmp_path, commands, profile=profile, failed_output=failed_output)

    assert passed
    assert commands.words() == ["lint", "full-tests"]
    assert profile.asked == []


def test_the_whole_repo_run_is_never_selected(tmp_path: Path) -> None:
    commands = Commands()
    profile = Profile([["selected"]])
    tier1 = build_tier1(
        run=commands,
        changed=lambda *a: CHANGED,
        profile=profile,
        repo=repo_config(tmp_path),
    )

    tier1(cwd=tmp_path, base="main", whole_repo=True, failed_output=FAILED_OUTPUT)

    assert "selected" not in commands.words()
    assert profile.asked == []


class TwoProjectsNoSelector(Commands):
    """A template whose program is missing: the first project's `select` cannot start."""

    def __call__(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
        if command[0] == "select":
            self.ran.append(command)
            self.directories.append(cwd)
            raise FileNotFoundError(command[0])
        return super().__call__(command, cwd=cwd)


def two_projects(tmp_path: Path, commands: Commands) -> tuple[bool, str]:
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
    return fix_round(
        tmp_path,
        commands,
        mode="command",
        command=TEMPLATE,
        projects=[ProjectConfig(path="a"), ProjectConfig(path="b")],
        changed=["a/x.py", "b/y.py"],
    )


def test_a_selector_that_cannot_start_leaves_no_project_unlinted(tmp_path: Path) -> None:
    commands = TwoProjectsNoSelector()

    passed, _ = two_projects(tmp_path, commands)

    assert passed
    lint = PythonUvProfile().lint_command("main")
    linted = {d.name for c, d in zip(commands.ran, commands.directories, strict=True) if c == lint}
    assert linted == {"a", "b"}


def test_a_lint_failure_in_a_project_the_selection_never_reached_still_fails(
    tmp_path: Path,
) -> None:
    class LintFailsInB(TwoProjectsNoSelector):
        def __call__(self, command: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
            if command == PythonUvProfile().lint_command("main") and cwd.name == "b":
                self.ran.append(command)
                self.directories.append(cwd)
                return subprocess.CompletedProcess(command, 1, "E501 in b", "")
            return super().__call__(command, cwd=cwd)

    passed, output = two_projects(tmp_path, LintFailsInB())

    assert not passed
    assert "E501 in b" in output


def test_a_selector_that_picks_nothing_is_a_selected_pass_the_full_suite_confirms(
    tmp_path: Path,
) -> None:
    nothing = Profile().no_tests_collected_exit
    commands = Commands(selected=(nothing, "no tests ran"))

    passed, _ = fix_round(tmp_path, commands)

    assert passed
    assert commands.words() == ["lint", "selected", "full-tests"]


def test_a_disagreement_is_logged(tmp_path: Path) -> None:
    commands = Commands(**{"full-tests": (1, "1 test failed")})
    log: list[str] = []

    fix_round(tmp_path, commands, log=log)

    assert sum("full suite failed" in line for line in log) == 1
