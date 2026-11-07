"""A unit-test run the machine was suspended in is rerun, not judged (spec: suspended-check-run).

Unit-test runs over the fake machine of `tests/failure_bundle_fakes.py`, whose parallel test
run prints the duration pytest measured itself and moves a fake wall clock by the time the host
says it took; the gap between the two is the suspend. The ledger is read as it is written.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import NamedTuple, cast

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import FailedOnBase, FlakeFound
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.conftest import make_installation
from tests.failure_bundle_fakes import START, BundleMachine, BundleProfile, storms


class Attempt(NamedTuple):
    """What one parallel test run did: its exit status, the duration pytest printed for it and
    the wall time the host spent."""

    exit: int
    own: float
    wall: float
    # A line printed ahead of pytest's summary that holds an `in <n>s` of its own.
    noise: str = ""


# A failing run whose wall time is far beyond its own duration: the machine slept through it.
SUSPENDED = Attempt(1, 2127, 8118)
# The same sort of run with an `in <n>s` in the output before the summary line.
NOISY = "E   AssertionError: assert '5 passed in 0.03s' == 'retrying in 1s'\n"
CLEAN = Attempt(0, 12, 12)


class Wall:
    """A fake wall clock the machine moves."""

    def __init__(self) -> None:
        self.elapsed = 0.0

    def __call__(self) -> datetime:
        return START + timedelta(seconds=self.elapsed)


class SuspendedMachine(BundleMachine):
    """The bundle machine whose parallel test runs go as `attempts` say, in order."""

    def __init__(self, root: Path, wall: Wall, attempts: list[Attempt]) -> None:
        super().__init__(root, reruns=[1, 1])
        self.wall = wall
        self.attempts = list(attempts)
        self.test_runs = 0

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        done = super().__call__(command, **kwargs)
        if command[0] in ("lint", "git") or command[-2:] == ["--version", "--version"]:
            return done
        if any("::" in argument for argument in command):
            return done
        if "-m" in command and command[command.index("-m") + 1] == "serial":
            # The serial half of a run, which follows its parallel half.
            return subprocess.CompletedProcess(command, 0, "1 passed in 0.01s\n", "")
        attempt = self.attempts[self.test_runs]
        self.test_runs += 1
        self.wall.elapsed += attempt.wall
        if attempt.exit == 0:
            output = f"5 passed in {attempt.own:.2f}s\n"
        else:
            output = attempt.noise + done.stdout.replace("in 0.01s", f"in {attempt.own:.2f}s")
        return subprocess.CompletedProcess(command, attempt.exit, output, "")


def run(
    scratch: Path, tmp_path: Path, attempts: list[Attempt], installation: Installation
) -> tuple[SuspendedMachine, Path, object]:
    """One unit-test call; returns the machine, the ledger and the result (None when the call
    raised a flake or a failure on the base)."""
    wall = Wall()
    machine = SuspendedMachine(scratch, wall, attempts)
    ledger = tmp_path / "test-runs.jsonl"
    unit_test = build_unit_test(
        profile=cast(ToolchainProfile, BundleProfile()),
        run=machine,
        changed=lambda *a: ["tests/test_one.py"],
        failures_dir=tmp_path / "bundles",
        test_runs=ledger,
        installation=installation,
        now=wall,
        machine=lambda: {"load": [0.1] * 3, "cpus": 4},
    )
    try:
        result: object = unit_test(cwd=scratch, base="main")
    except (FlakeFound, FailedOnBase):
        result = None
    return machine, ledger, result


def rows(ledger: Path) -> list[dict]:
    return [json.loads(line) for line in ledger.read_text().splitlines()]


@pytest.fixture
def installation(scratch: Path) -> Installation:
    return make_installation(scratch, global_limits=dict(max_flakes_per_run=2))


def test_a_suspended_failing_run_is_not_judged_and_the_checks_run_again(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    machine, ledger, result = run(scratch, tmp_path, [SUSPENDED, CLEAN], installation)

    assert machine.test_runs == 2
    assert result == (True, "")
    first, second = rows(ledger)
    assert first["outcome"] == "disturbed"
    assert first["disturbed_seconds"] == pytest.approx(8118 - 2127, abs=5)
    assert second["outcome"] == "passed"
    assert second.get("disturbed_seconds") is None


def test_a_suspended_run_is_neither_a_flake_nor_a_storm(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    machine, _, result = run(scratch, tmp_path, [SUSPENDED, CLEAN], installation)

    assert result == (True, "")
    assert not [c for c in machine.commands if any("::" in a for a in c)], "no failed test reran"
    assert storms(installation) == []


def test_a_second_disturbed_run_holds_the_unit_with_a_note_naming_the_suspend(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    machine, ledger, result = run(scratch, tmp_path, [SUSPENDED, SUSPENDED, CLEAN], installation)

    assert machine.test_runs == 2, "the checks ran once more and no third time"
    assert isinstance(result, tuple)
    passed, output = result
    assert not passed
    assert "suspend" in output.lower()
    assert [row["outcome"] for row in rows(ledger)] == ["disturbed", "disturbed"]


def test_a_slow_run_whose_clocks_agree_is_judged(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    machine, ledger, result = run(scratch, tmp_path, [Attempt(1, 8000, 8100)], installation)

    assert machine.test_runs == 1
    assert result != (True, "")
    (row,) = rows(ledger)
    assert row["outcome"] != "disturbed"
    assert row.get("disturbed_seconds") is None


def test_a_gap_below_the_limit_is_judged(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    machine, ledger, result = run(scratch, tmp_path, [Attempt(1, 100, 100 + 250)], installation)

    assert machine.test_runs == 1
    assert result != (True, "")
    (row,) = rows(ledger)
    assert row["outcome"] != "disturbed"


def test_the_duration_is_the_final_summary_lines_not_an_earlier_one() -> None:
    output = (
        "E   AssertionError: assert '5 passed in 0.03s' == 'retrying in 1s'\n"
        "=========== short test summary info ===========\n"
        "FAILED test_one.py::test_plain - assert 1 == 2\n"
        "=========== 1 failed, 4 passed in 2127.00s (0:35:27) ===========\n"
    )

    assert BundleProfile().parse_test_summary(output) == (4, 1, 0, 2127.0)


def test_a_failing_run_with_an_earlier_in_n_s_line_is_judged_on_its_real_duration(
    scratch: Path, tmp_path: Path, installation: Installation
) -> None:
    attempt = Attempt(1, 2127, 2200, noise=NOISY)

    machine, ledger, result = run(scratch, tmp_path, [attempt], installation)

    assert machine.test_runs == 1
    assert result != (True, "")
    (row,) = rows(ledger)
    assert row["outcome"] != "disturbed"
