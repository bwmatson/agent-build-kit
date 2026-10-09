"""A failed tier 1 test is run again alone, twice, to tell a flake from a failure
(spec: flaky-tests).

The profile's pytest hooks read the output of a real pytest run, recorded under
`tests/fixtures/external/pytest/`. Tier 1 itself runs through a fake runner that answers
with that output, since what a runner returns is a process's exit status and text.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.pipeline.flakes import FlakeFound
from agent_build_kit.pipeline.wiring import build_tier1
from agent_build_kit.profiles.base import ToolchainProfile
from agent_build_kit.profiles.python_uv import PythonUvProfile

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "external" / "pytest"

# What `console_failures.txt` records: four failures and a fixture error, across two files,
# one in a class and one a parametrised case.
FAILED = [
    "test_one.py::test_plain",
    "test_one.py::TestGroup::test_method",
    "test_one.py::test_cases[2]",
    "test_two.py::test_other",
    "test_one.py::test_setup_error",
]

WORKSPACE_RUN = [
    "uv",
    "run",
    "--package",
    "svc-a",
    "--isolated",
    "pytest",
    "svc-a",
    "-n",
    "auto",
    "--maxprocesses=8",
    "-m",
    "not serial",
    "-q",
]
ROOT_RUN = [
    "uv",
    "run",
    "--no-project",
    "--isolated",
    "--with",
    "pytest",
    "--with",
    "pytest-xdist",
    "pytest",
    "tests",
    "-n",
    "auto",
    "--maxprocesses=8",
    "-m",
    "not serial",
    "-q",
]


def recorded_failure() -> str:
    """The recorded console output without the header naming the tool version."""
    return (RECORDED / "console_failures.txt").read_text().split("\n", 1)[1]


# --- the profile's hooks --------------------------------------------------------


def test_the_failed_identifiers_are_read_from_a_recorded_run() -> None:
    assert PythonUvProfile().failed_tests(recorded_failure()) == FAILED


def test_a_run_that_is_not_a_test_run_names_no_failed_tests() -> None:
    lint = (
        "$ uv run pre-commit run --from-ref main --to-ref HEAD (exit 1)\n"
        "ruff.....................................................................Failed\n"
        "- hook id: ruff\n- exit code: 1\n\nsrc/app.py:1:1: F401 `os` imported but unused\n"
    )

    assert PythonUvProfile().failed_tests(lint) == []
    assert PythonUvProfile().failed_tests("3 passed in 0.01s\n") == []


@pytest.mark.parametrize("command", [WORKSPACE_RUN, ROOT_RUN])
def test_the_serial_command_runs_only_the_failed_tests_in_the_same_environment(
    command: list[str],
) -> None:
    tests = ["svc-a/tests/test_x.py::test_y", "svc-a/tests/test_x.py::TestZ::test_w[3]"]

    rerun = PythonUvProfile().serial_rerun_command(command, tests)

    head = command[: command.index("pytest") + 1]
    assert rerun[: len(head)] == head, "the environment the run was made in is kept"
    assert set(tests) <= set(rerun)
    for gone in ("-n", "auto", "--maxprocesses=8", "-m", "not serial", "svc-a", "tests"):
        assert gone not in rerun[len(head) :], (
            f"{gone!r} would run more than the failed tests, or in parallel"
        )


# --- tier 1 --------------------------------------------------------------------


class HookedProfile(PythonUvProfile):
    """The python-uv profile running one lint command and one parallel test command."""

    def lint_command(self, base: str) -> list[str]:
        return ["lint"]

    def test_commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str]
    ) -> list[list[str]]:
        return [["uv", "run", "pytest", "-n", "auto", "-q"]]


class WithoutHooks:
    """`HookedProfile` offering neither of the flake hooks."""

    def __init__(self) -> None:
        self.inner = HookedProfile()

    def __getattr__(self, name: str):
        if name in ("failed_tests", "serial_rerun_command"):
            raise AttributeError(name)
        return getattr(self.inner, name)


class Runs:
    """Answers each command as the process would: lint passes, the parallel run fails with
    the recorded output, and each serial rerun exits as `reruns` says."""

    def __init__(self, *, reruns: list[int], lint_exit: int = 0, run_exit: int = 1) -> None:
        self.reruns = list(reruns)
        self.lint_exit = lint_exit
        self.run_exit = run_exit
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        if command == ["lint"]:
            output = "ruff.....Failed\n- hook id: ruff\n" if self.lint_exit else ""
            return subprocess.CompletedProcess(command, self.lint_exit, output, "")
        if not any("::" in argument for argument in command):
            return subprocess.CompletedProcess(command, self.run_exit, recorded_failure(), "")
        exit_code = self.reruns.pop(0)
        output = "5 passed in 0.03s\n" if exit_code == 0 else "1 failed, 4 passed in 0.03s\n"
        return subprocess.CompletedProcess(command, exit_code, output, "")

    @property
    def serial_runs(self) -> list[list[str]]:
        return [c for c in self.commands if any("::" in argument for argument in c)]


def tier1(profile: object, runs: Runs, tmp_path: Path) -> tuple[bool, str]:
    return build_tier1(
        profile=cast(ToolchainProfile, profile), run=runs, changed=lambda *a: ["tests/test_one.py"]
    )(cwd=tmp_path, base="main")


def test_failed_tests_that_pass_both_serial_reruns_are_a_flake_not_a_failure(
    tmp_path: Path,
) -> None:
    runs = Runs(reruns=[0, 0])

    with pytest.raises(FlakeFound) as found:
        tier1(HookedProfile(), runs, tmp_path)

    flakes = found.value.flakes
    assert [flake.test for flake in flakes] == FAILED
    assert len(runs.serial_runs) == 2, "twice, not once"
    for rerun in runs.serial_runs:
        assert set(FAILED) <= set(rerun)
        assert "-n" not in rerun, "serially"
    for flake in flakes:
        assert flake.command == shlex.join(["uv", "run", "pytest", "-n", "auto", "-q"])
        assert "short test summary info" in flake.output, "the first failure's output is kept"
        assert "assert 1 == 2" in flake.output


def test_a_test_that_fails_again_alone_fails_the_unit_as_before(tmp_path: Path) -> None:
    runs = Runs(reruns=[0, 1])

    passed, message = tier1(HookedProfile(), runs, tmp_path)

    assert not passed
    assert len(runs.serial_runs) == 2, "both reruns were made before it was judged"
    assert message.startswith("$ uv run pytest -n auto -q (exit 1)")
    assert "short test summary info" in message, "the output is what a retry is told"


def test_a_test_that_fails_its_first_rerun_fails_the_unit_as_before(tmp_path: Path) -> None:
    runs = Runs(reruns=[1, 0])

    passed, message = tier1(HookedProfile(), runs, tmp_path)

    assert not passed
    assert runs.serial_runs, "the failed tests were run again before it was judged"
    assert message.startswith("$ uv run pytest -n auto -q (exit 1)")


def test_a_profile_without_the_hooks_fails_the_unit_as_before(tmp_path: Path) -> None:
    runs = Runs(reruns=[0, 0])

    passed, message = tier1(WithoutHooks(), runs, tmp_path)

    assert not passed
    assert message.startswith("$ uv run pytest -n auto -q (exit 1)")
    assert runs.serial_runs == [], "nothing was run again"


def test_a_lint_failure_is_never_run_again(tmp_path: Path) -> None:
    runs = Runs(reruns=[0, 0], lint_exit=1)

    passed, message = tier1(HookedProfile(), runs, tmp_path)

    assert not passed
    assert message.startswith("$ lint (exit 1)")
    assert runs.serial_runs == []
