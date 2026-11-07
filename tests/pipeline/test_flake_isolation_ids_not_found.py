"""A rerun of failed tests survives ids pytest cannot find (spec: test-rerun-ids).

The fake runner answers as pytest does: a command naming an id it cannot find ends in a usage
error (exit 4) with an `ERROR: not found:` line for each such id and runs nothing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import cast

from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from agent_build_kit.profiles.python_uv import PythonUvProfile

SPACED = [
    f"tests/test_one.py::test_cases[no conversation found with session id sess-{n}]"
    for n in range(16)
]
PLAIN = ["tests/test_one.py::test_plain", "tests/test_one.py::TestGroup::test_method"]


class HookedProfile(PythonUvProfile):
    def lint_command(self, base: str) -> list[str]:
        return ["lint"]

    def _commands(
        self, repo: Path, changed: list[str], *, root_extras: list[str], **_workers: object
    ) -> list[list[str]]:
        return [["uv", "run", "pytest", "-n", "auto", "-q"]]

    test_commands = _commands


class Runs:
    """Lint passes, the parallel run fails on `failed`, and a serial rerun names `missing` as
    not found, or else fails again."""

    def __init__(self, failed: list[str], missing: list[str]) -> None:
        self.failed = failed
        self.missing = missing
        self.serial_runs: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if command == ["lint"]:
            return subprocess.CompletedProcess(command, 0, "", "")
        if not any("::" in argument for argument in command):
            lines = "".join(f"FAILED {test} - AssertionError: no\n" for test in self.failed)
            return subprocess.CompletedProcess(
                command, 1, f"=== short test summary info ===\n{lines}", ""
            )
        self.serial_runs.append(command)
        absent = [test for test in self.missing if test in command]
        if absent:
            lines = "".join(
                f"ERROR: not found: {test} (no match in any of [<Module test_one.py>])\n"
                for test in absent
            )
            return subprocess.CompletedProcess(command, 4, "", lines)
        return subprocess.CompletedProcess(command, 1, "1 failed, 4 passed in 0.03s\n", "")


def unit_test(runs: Runs, log: list[str], tmp_path: Path) -> tuple[bool, str]:
    return build_unit_test(
        profile=cast(ToolchainProfile, HookedProfile()),
        run=runs,
        changed=lambda *a: ["tests/test_one.py"],
        log=log.append,
    )(cwd=tmp_path, base="main")


def test_the_ids_pytest_cannot_find_are_left_out_named_and_the_others_rerun(
    tmp_path: Path,
) -> None:
    runs = Runs([*PLAIN, *SPACED], missing=SPACED)
    log: list[str] = []

    passed, _ = unit_test(runs, log, tmp_path)

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
    runs = Runs(SPACED, missing=SPACED)
    log: list[str] = []

    passed, _ = unit_test(runs, log, tmp_path)

    assert not passed
    assert len(runs.serial_runs) == 1, "only the attempt that found none of them"
    assert set(runs.serial_runs[0]) >= set(SPACED)
    assert all(test in "\n".join(log) for test in SPACED)
