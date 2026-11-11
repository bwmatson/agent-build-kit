"""A failed test in the unit-test run is run again alone, twice, to tell a flake from a failure
(spec: flaky-tests).

The profile's pytest hooks read the output of a real pytest run, recorded under
`tests/fixtures/external/pytest/`. Unit-test itself runs through a fake runner that answers
with that output, since what a runner returns is a process's exit status and text.
"""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.pipeline.flakes import FlakeFound
from agent_build_kit.pipeline.red_check import REPORT_MARK
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from agent_build_kit.profiles.node_npm import NodeNpmProfile
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


TESTS = ["svc-a/tests/test_x.py::test_y", "svc-a/tests/test_x.py::TestZ::test_w[3]"]


def test_the_serial_command_for_a_workspace_member_keeps_its_package_and_runs_only_the_tests() -> (
    None
):
    assert PythonUvProfile().serial_rerun_command(WORKSPACE_RUN, TESTS) == [
        "uv",
        "run",
        "--package",
        "svc-a",
        "--isolated",
        "pytest",
        *TESTS,
        "-q",
    ]


def test_the_serial_command_for_the_root_tests_keeps_every_with_extra() -> None:
    assert PythonUvProfile().serial_rerun_command(ROOT_RUN, TESTS) == [
        "uv",
        "run",
        "--no-project",
        "--isolated",
        "--with",
        "pytest",
        "--with",
        "pytest-xdist",
        "pytest",
        *TESTS,
        "-q",
    ]


# --- unit-test --------------------------------------------------------------------


class HookedProfile(PythonUvProfile):
    """The python-uv profile running one lint command and one parallel test command."""

    def lint_command(self, base: str) -> list[str]:
        return ["lint"]

    def _commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str], **_workers: object
    ) -> list[list[str]]:
        return [["uv", "run", "pytest", "-n", "auto", "-q"]]

    # Assigned, not defined: a scan for changed tests takes any `def test_*` for one.
    test_commands = _commands


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


def unit_test(profile: object, runs: Runs, tmp_path: Path) -> tuple[bool, str]:
    return build_unit_test(
        profile=cast(ToolchainProfile, profile), run=runs, changed=lambda *a: ["tests/test_one.py"]
    )(cwd=tmp_path, base="main")


def test_failed_tests_that_pass_both_serial_reruns_are_a_flake_not_a_failure(
    tmp_path: Path,
) -> None:
    runs = Runs(reruns=[0, 0])

    with pytest.raises(FlakeFound) as found:
        unit_test(HookedProfile(), runs, tmp_path)

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

    passed, message = unit_test(HookedProfile(), runs, tmp_path)

    assert not passed
    assert len(runs.serial_runs) == 2, "both reruns were made before it was judged"
    assert message.startswith("$ uv run pytest -n auto -q (exit 1)")
    assert "short test summary info" in message, "the output is what a retry is told"


def test_a_test_that_fails_its_first_rerun_fails_the_unit_as_before(tmp_path: Path) -> None:
    runs = Runs(reruns=[1, 0])

    passed, message = unit_test(HookedProfile(), runs, tmp_path)

    assert not passed
    assert runs.serial_runs, "the failed tests were run again before it was judged"
    assert message.startswith("$ uv run pytest -n auto -q (exit 1)")


def test_a_profile_without_the_hooks_fails_the_unit_as_before(tmp_path: Path) -> None:
    runs = Runs(reruns=[0, 0])

    passed, message = unit_test(WithoutHooks(), runs, tmp_path)

    assert not passed
    assert message.startswith("$ uv run pytest -n auto -q (exit 1)")
    assert runs.serial_runs == [], "nothing was run again"


def test_a_lint_failure_is_never_run_again(tmp_path: Path) -> None:
    runs = Runs(reruns=[0, 0], lint_exit=1)

    passed, message = unit_test(HookedProfile(), runs, tmp_path)

    assert not passed
    assert message.startswith("$ lint (exit 1)")
    assert runs.serial_runs == []


# --- ids pytest cannot find -----------------------------------------------------------

SPACED = [
    f"tests/test_one.py::test_cases[no conversation found with session id sess-{n}]"
    for n in range(16)
]
PLAIN = ["tests/test_one.py::test_plain", "tests/test_one.py::TestGroup::test_method"]


def test_a_summary_names_a_parametrized_id_with_spaces_whole_and_leaves_the_reason_out() -> None:
    odd = "tests/a/test_x.py::test_y[a - b]"
    output = (
        "=========== short test summary info ===========\n"
        f"FAILED {SPACED[0]} - AssertionError: no conversation\n"
        "FAILED tests/a/test_x.py::test_plain - AssertionError: no\n"
        f"ERROR {SPACED[1]}\n"
        "ERROR tests/a/test_x.py::TestGroup::test_setup[a b] - RuntimeError: boom\n"
        f"FAILED {odd} - assert x[1] == 2\n"
    )

    assert PythonUvProfile().failed_tests(output) == [
        SPACED[0],
        "tests/a/test_x.py::test_plain",
        SPACED[1],
        "tests/a/test_x.py::TestGroup::test_setup[a b]",
        odd,
    ]


class NotFoundRuns(Runs):
    """Answers a serial rerun naming a test of `missing` as pytest does: a usage error whose
    stderr names the absolute path and the names without the parametrization, then says why on
    the next line. Any other rerun fails again."""

    def __init__(self, failed: list[str], missing: list[str]) -> None:
        super().__init__(reruns=[])
        self.failed = failed
        self.missing = missing

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if command == ["lint"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if not any("::" in argument for argument in command):
            lines = "".join(f"FAILED {test} - AssertionError: no\n" for test in self.failed)
            return subprocess.CompletedProcess(
                command, 1, f"=== short test summary info ===\n{lines}", ""
            )
        self.commands.append(command)
        absent = [test for test in dict.fromkeys(self.missing) if test in command]
        if absent:
            where = Path(str(kwargs["cwd"]))
            lines = "".join(
                f"ERROR: not found: {where / test.split('[')[0]}\n"
                "(no match in any of [<Module test_one.py>])\n"
                for test in dict.fromkeys(test.split("[")[0] for test in absent)
            )
            return subprocess.CompletedProcess(command, 4, "", lines)
        return subprocess.CompletedProcess(command, 1, "1 failed, 4 passed in 0.03s\n", "")


def test_the_ids_pytest_cannot_find_are_left_out_named_and_the_others_rerun(
    tmp_path: Path,
) -> None:
    runs = NotFoundRuns([*PLAIN, *SPACED], missing=SPACED)
    log: list[str] = []

    passed, _ = build_unit_test(
        profile=cast(ToolchainProfile, HookedProfile()),
        run=runs,
        changed=lambda *a: ["tests/test_one.py"],
        log=log.append,
    )(cwd=tmp_path, base="main")

    assert not passed, "the failures that stand fail the unit"
    assert set(runs.serial_runs[0]) >= {*PLAIN, *SPACED}, "the first rerun names every id"
    reduced = runs.serial_runs[1]
    assert set(PLAIN) <= set(reduced)
    assert not set(SPACED) & set(reduced)
    named = "\n".join(log)
    for test in SPACED:
        assert test in named


def test_when_every_id_is_not_found_nothing_is_rerun_and_every_failure_stands(
    tmp_path: Path,
) -> None:
    runs = NotFoundRuns(SPACED, missing=SPACED)
    log: list[str] = []

    passed, _ = build_unit_test(
        profile=cast(ToolchainProfile, HookedProfile()),
        run=runs,
        changed=lambda *a: ["tests/test_one.py"],
        log=log.append,
    )(cwd=tmp_path, base="main")

    assert not passed
    assert len(runs.serial_runs) == 1, "only the attempt that found none of them"
    assert set(runs.serial_runs[0]) >= set(SPACED)
    assert all(test in "\n".join(log) for test in SPACED)


# --- the node profile ---------------------------------------------------------------


class NodeRuns:
    """Answers the node profile's commands: the whole run fails with a recorded report and each
    filtered rerun exits as the next of `reruns` says."""

    def __init__(self, whole: list[str], reruns: list[int]) -> None:
        self.whole = whole
        self.reruns = list(reruns)
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        self.commands.append(command)
        if command == self.whole:
            report = RECORDED.parent / "vitest" / "assertion_only.xml"
            return subprocess.CompletedProcess(
                command, 1, f"{REPORT_MARK}\n{report.read_text()}", ""
            )
        if command == ["true"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        return subprocess.CompletedProcess(command, self.reruns.pop(0), "", "")


class QuietNodeProfile(NodeNpmProfile):
    def lint_command(self, base: str) -> list[str]:
        return ["true"]


def test_a_failed_node_test_that_passes_both_serial_reruns_is_a_flake(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "app"}')
    profile = QuietNodeProfile()
    (whole,) = profile.test_commands_all(tmp_path, root_extras=[])
    runs = NodeRuns(whole, reruns=[0, 0])

    with pytest.raises(FlakeFound) as found:
        build_unit_test(profile=profile, run=runs, changed=lambda *a: ["src/a.test.ts"])(
            cwd=tmp_path, base="main"
        )

    assert [flake.test for flake in found.value.flakes] == ["a.test.ts::adds"]
    assert len(runs.commands) == 4, "lint, the run, then two serial reruns"
