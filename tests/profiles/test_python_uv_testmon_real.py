"""The profile's selection against a real pytest and a real pytest-testmon.

The profile records what each test executes with one command and selects with another; the
claim "a selection selects" is only as good as what the real tools do with those commands, so
a small project is built, recorded and changed here. The tool is fetched with `--with`, so the
tests need the network and carry the `integration` marker (run them with `-m integration`).

Found, on Python 3.14.7 with coverage 7.17.0 and pytest-testmon 2.2.0: the commands as the
profile builds them print no "Dynamic contexts aren't supported" warning and miss no selection,
so `COVERAGE_CORE=ctrace` is not pinned. Forcing `COVERAGE_CORE=sysmon` in the environment does
make the warning appear, so the check below can see it. An empty selection exits 0 ("deselected"
or, under xdist, "no tests ran"), not 5; the pipeline counts both as a pass.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.profiles.python_uv import PROFILE

pytestmark = pytest.mark.integration

NO_TESTS_COLLECTED = 5
DYNAMIC_CONTEXTS = "Dynamic contexts aren't supported"

PYPROJECT = """\
[project]
name = "tiny"
version = "0"
requires-python = ">=3.12"
dependencies = []

[dependency-groups]
dev = ["pytest", "pytest-xdist"]

[tool.uv]
package = false

[tool.pytest.ini_options]
addopts = "-m 'not slow'"
pythonpath = ["."]
markers = ["slow: excluded by addopts", "serial: runs alone"]
"""

CALC = """\
def add(a, b):
    return a + b


def mul(a, b):
    return a * b


def only_serial(x):
    return x + 0
"""

TESTS = """\
import pytest

from calc import add, mul, only_serial


def test_add():
    assert add(1, 2) == 3


def test_mul():
    assert mul(2, 3) == 6


def test_both():
    assert mul(add(1, 1), 3) == 6


def test_unrelated():
    assert 1 + 1 == 2


@pytest.mark.slow
def test_slow_add():
    assert add(2, 2) == 4


@pytest.mark.serial
def test_serial_add():
    assert add(3, 3) == 6
    assert only_serial(3) == 3
"""

BROKEN_CALC = CALC.replace("a + b", "a - b")
AFFECTED = {"test_add", "test_both"}


class Tiny:
    """A project in a folder, its pytest commands as the profile builds them, and its data."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.seed = root.parent / f"{root.name}-seed" / "affected"
        self.seed.parent.mkdir()
        (root / "tests").mkdir(parents=True)
        (root / "pyproject.toml").write_text(PYPROJECT)
        (root / "calc.py").write_text(CALC)
        (root / "tests" / "test_calc.py").write_text(TESTS)
        # The parallel pass, then the serial pass: what a full run is.
        self.parallel, self.serial = PROFILE.test_commands_all(root, root_extras=[])

    def run(self, command: list[str]) -> subprocess.CompletedProcess[str]:
        env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "PYTEST_ADDOPTS")}
        return subprocess.run(
            [*command, "-rf", "-p", "no:cacheprovider"],
            cwd=self.root,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

    def record(self) -> None:
        for command in (self.parallel, self.serial):
            done = self.run(PROFILE.seeding_command(command, self.seed))
            assert done.returncode in (0, NO_TESTS_COLLECTED), done.stdout + done.stderr
            assert DYNAMIC_CONTEXTS not in done.stdout + done.stderr

    def select(self, command: list[str] | None = None) -> subprocess.CompletedProcess[str]:
        return self.run(PROFILE.seeding_command(command or self.parallel, self.seed, select=True))

    def break_add(self) -> None:
        (self.root / "calc.py").write_text(BROKEN_CALC)


def failed(output: str) -> set[str]:
    return set(re.findall(r"^FAILED tests/test_calc\.py::(\w+)", output, re.MULTILINE))


def ran(output: str) -> set[str]:
    """The tests a `-v` run reported."""
    return set(re.findall(r"tests/test_calc\.py::(\w+)", output))


@pytest.fixture
def tiny(tmp_path: Path) -> Tiny:
    project = Tiny(tmp_path / "tiny")
    project.record()
    return project


def test_nothing_changed_selects_nothing(tiny: Tiny) -> None:
    # Measured: testmon deselects every test and pytest exits 0 ("6 deselected"); xdist's
    # "no tests ran" exits 0 too. Exit 5 is what a run that collects nothing at all gives,
    # and the pipeline counts both as a pass.
    serial = tiny.select(tiny.serial)
    parallel = tiny.select()

    for done in (serial, parallel):
        assert done.returncode in (0, NO_TESTS_COLLECTED), done.stdout + done.stderr
        assert "passed" not in done.stdout and "failed" not in done.stdout
        assert "deselected" in done.stdout or "no tests ran" in done.stdout
        assert "deactivated" not in done.stdout
        assert DYNAMIC_CONTEXTS not in done.stdout + done.stderr


def test_a_changed_function_selects_the_tests_that_reach_it_and_fails_as_a_full_run_does(
    tiny: Tiny,
) -> None:
    tiny.break_add()

    selected = tiny.select([*tiny.parallel, "-v"])
    everything = tiny.run([*tiny.parallel, "-v"])

    assert "deactivated" not in selected.stdout
    assert DYNAMIC_CONTEXTS not in selected.stdout + selected.stderr
    assert ran(selected.stdout) == AFFECTED
    assert failed(selected.stdout) == AFFECTED
    assert failed(everything.stdout) == failed(selected.stdout)


def test_a_slow_test_stays_out_even_when_it_reaches_the_changed_function(tiny: Tiny) -> None:
    tiny.break_add()

    selected = tiny.select([*tiny.parallel, "-v"])

    assert {"test_add", "test_both"} <= ran(selected.stdout)
    assert "test_slow_add" not in selected.stdout
    assert "test_serial_add" not in selected.stdout


def empty(output: str) -> bool:
    return ("deselected" in output or "no tests ran" in output) and "passed" not in output


def test_a_full_run_in_two_passes_leaves_data_for_both(tiny: Tiny) -> None:
    # With no data a pass selects every test, so each pass is shown to hold data by a change
    # that only the other pass's tests reach: it must select nothing.
    (tiny.root / "calc.py").write_text(CALC.replace("a * b", "a * b + 1"))

    serial = tiny.select([*tiny.serial, "-v"])
    parallel = tiny.select([*tiny.parallel, "-v"])

    assert empty(serial.stdout), serial.stdout
    assert {"test_mul", "test_both"} <= ran(parallel.stdout)
    assert "deactivated" not in parallel.stdout + serial.stdout


def test_a_change_only_the_serial_pass_reaches_selects_nothing_in_the_parallel_pass(
    tiny: Tiny,
) -> None:
    (tiny.root / "calc.py").write_text(CALC.replace("x + 0", "x + 1"))

    # The serial pass goes first: a run that executes tests updates the data it shares.
    serial = tiny.select([*tiny.serial, "-v"])
    parallel = tiny.select([*tiny.parallel, "-v"])

    assert empty(parallel.stdout), parallel.stdout
    assert failed(serial.stdout) == {"test_serial_add"}
