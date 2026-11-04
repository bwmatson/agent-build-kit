"""A ledger row and the conditions of a flake, storm or pre-existing record say whether the host
was loaded, and a failed-test entry which worker ran it and whether it hit its time limit (spec:
test-failure-evidence, "The record says whether the host was loaded").

Unit-test runs over the fake machine of `tests/failure_bundle_fakes.py`. The machine sample is
injected, so the load and the CPU count are the test's own. A row written before the fields is a
JSON line without them.
"""

from __future__ import annotations

import contextlib
import json
import subprocess
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.flakes import FailedOnBase, FlakeFound
from agent_build_kit.pipeline.run_log import TestRun
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.conftest import make_installation
from tests.failure_bundle_fakes import START, BundleMachine, BundleProfile, storms

TIMED_OUT = "test_one.py::test_plain"
OTHER = "test_two.py::test_other"
THRESHOLD = 2.0
CPUS = 4

# What an xdist run prints at `-v`: the worker of each result, then the short summary.
WORKERS_OUTPUT = f"""\
[gw2] [ 40%] FAILED {TIMED_OUT}
[gw0] [ 80%] FAILED {OTHER}
=========================== short test summary info ============================
FAILED {TIMED_OUT} - Failed: Timeout >60.0s
FAILED {OTHER} - assert [] == [1]
2 failed in 61.00s
"""


class WorkersMachine(BundleMachine):
    """The bundle machine whose test run prints `WORKERS_OUTPUT`."""

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        done = super().__call__(command, **kwargs)
        if done.returncode == 1 and not any("::" in argument for argument in command):
            return subprocess.CompletedProcess(command, 1, WORKERS_OUTPUT, "")
        return done


def sampling(load: float, *, cpus: int | None = CPUS) -> Callable[[], dict[str, object]]:
    """A machine sample with the one-minute load `load`."""
    sample: dict[str, object] = {"load": [load] * 3}
    if cpus is not None:
        sample["cpus"] = cpus
    return lambda: dict(sample)


def run(
    scratch: Path,
    machine: BundleMachine,
    tmp_path: Path,
    installation: Installation,
    sample: Callable[[], dict[str, object]],
) -> Path:
    """One unit-test run; returns its ledger."""
    ledger = tmp_path / "test-runs.jsonl"
    clock = iter(START + timedelta(seconds=10 * n) for n in range(100))
    unit_test = build_unit_test(
        profile=cast(ToolchainProfile, BundleProfile()),
        run=machine,
        changed=lambda *a: ["tests/test_one.py"],
        failures_dir=tmp_path / "bundles",
        test_runs=ledger,
        installation=installation,
        now=lambda: next(clock),
        machine=sample,
    )
    with contextlib.suppress(FlakeFound, FailedOnBase):
        unit_test(cwd=scratch, base="main")
    return ledger


def row(ledger: Path) -> dict:
    (line,) = ledger.read_text().splitlines()
    return json.loads(line)


@pytest.fixture
def loaded(scratch: Path) -> Installation:
    return make_installation(
        scratch, tests=dict(load_high_per_cpu=THRESHOLD), global_limits=dict(max_flakes_per_run=2)
    )


# --- the threshold ------------------------------------------------------------------


def test_the_threshold_is_a_per_cpu_setting_under_tests(loaded: Installation) -> None:
    assert loaded.config.model_dump()["tests"]["load_high_per_cpu"] == THRESHOLD


def test_the_threshold_has_a_positive_default(tmp_path: Path) -> None:
    assert make_installation(tmp_path).config.model_dump()["tests"]["load_high_per_cpu"] > 0


# --- the ledger row -----------------------------------------------------------------


def test_a_row_has_the_cpu_count_and_is_loaded_when_the_load_is_at_the_threshold_per_cpu(
    scratch: Path, tmp_path: Path, loaded: Installation
) -> None:
    ledger = run(
        scratch,
        BundleMachine(scratch, reruns=[], passing=True),
        tmp_path,
        loaded,
        sampling(THRESHOLD * CPUS),
    )

    assert row(ledger)["cpus"] == CPUS
    assert row(ledger)["load_high"] is True


def test_a_row_is_not_loaded_when_the_load_is_below_the_threshold_per_cpu(
    scratch: Path, tmp_path: Path, loaded: Installation
) -> None:
    ledger = run(
        scratch,
        BundleMachine(scratch, reruns=[], passing=True),
        tmp_path,
        loaded,
        sampling(THRESHOLD * CPUS - 1),
    )

    assert row(ledger)["cpus"] == CPUS
    assert row(ledger)["load_high"] is False


def test_a_row_is_loaded_when_only_the_load_at_the_end_is_high(
    scratch: Path, tmp_path: Path, loaded: Installation
) -> None:
    taken: list[int] = []

    def sample() -> dict[str, object]:
        taken.append(1)
        return {"load": [1.0 if len(taken) == 1 else 40.0] * 3, "cpus": CPUS}

    ledger = run(scratch, BundleMachine(scratch, reruns=[], passing=True), tmp_path, loaded, sample)

    assert row(ledger)["load_start"] == 1.0
    assert row(ledger)["load_high"] is True


def test_a_host_that_does_not_say_its_cpus_or_load_reads_as_unknown(
    scratch: Path, tmp_path: Path, loaded: Installation
) -> None:
    ledger = run(
        scratch,
        BundleMachine(scratch, reruns=[], passing=True),
        tmp_path,
        loaded,
        sampling(50.0, cpus=None),
    )

    assert row(ledger)["cpus"] is None
    assert row(ledger)["load_high"] is None, "not false: nothing says the host was idle"


# --- the failed-test entries --------------------------------------------------------


def test_a_failed_test_entry_keeps_its_worker_and_whether_it_hit_its_time_limit(
    scratch: Path, tmp_path: Path, loaded: Installation
) -> None:
    ledger = run(scratch, WorkersMachine(scratch, reruns=[1, 1]), tmp_path, loaded, sampling(1.0))

    detail = {entry["test"]: entry for entry in row(ledger)["failed_detail"]}
    assert detail[TIMED_OUT]["worker"] == "gw2"
    assert detail[TIMED_OUT]["time_limit"] is True
    assert detail[OTHER]["worker"] == "gw0"
    assert detail[OTHER]["time_limit"] is False
    assert TIMED_OUT in row(ledger)["failed"], "the list of ids stays as it was"


def test_a_passing_run_has_no_failed_entries(
    scratch: Path, tmp_path: Path, loaded: Installation
) -> None:
    ledger = run(
        scratch,
        BundleMachine(scratch, reruns=[], passing=True),
        tmp_path,
        loaded,
        sampling(1.0),
    )

    assert row(ledger)["failed_detail"] == []


# --- a row written before the fields ------------------------------------------------

OLD_ROW = {
    "unit": "add-marker/1",
    "started": START.isoformat(),
    "seconds": 12.5,
    "outcome": "failed",
    "failed": [TIMED_OUT],
    "load_start": 3.0,
    "load_end": 4.0,
    "workers": "auto",
    "tick": "t1",
    "units_running": [],
    "wait_seconds": 0.0,
}


def test_a_row_written_before_the_fields_loads_and_reads_as_unknown() -> None:
    old = TestRun.model_validate_json(json.dumps(OLD_ROW)).model_dump()

    assert old["cpus"] is None
    assert old["load_high"] is None
    assert old["failed_detail"] == []
    assert old["failed"] == [TIMED_OUT]


# --- the records' conditions --------------------------------------------------------


def flakes_under(
    scratch: Path, tmp_path: Path, installation: Installation, load: float
) -> tuple[dict[str, object], ...]:
    machine = BundleMachine(scratch, reruns=[0, 0])
    clock = iter(START + timedelta(seconds=10 * n) for n in range(100))
    unit_test = build_unit_test(
        profile=cast(ToolchainProfile, BundleProfile()),
        run=machine,
        changed=lambda *a: ["tests/test_one.py"],
        failures_dir=tmp_path / "bundles",
        installation=installation,
        now=lambda: next(clock),
        machine=sampling(load),
    )
    with pytest.raises(FlakeFound) as found:
        unit_test(cwd=scratch, base="main")
    return tuple(flake.conditions for flake in found.value.flakes)


def test_a_flakes_conditions_have_the_cpu_count_and_the_loaded_flag(
    scratch: Path, tmp_path: Path
) -> None:
    installation = make_installation(scratch, tests=dict(load_high_per_cpu=THRESHOLD))

    for conditions in flakes_under(scratch, tmp_path, installation, THRESHOLD * CPUS):
        assert conditions["cpus"] == CPUS
        assert conditions["load_high"] is True
        assert conditions["rerun_exits"] == [0, 0], "beside what they had"


def test_a_flake_met_on_an_idle_host_is_not_loaded(scratch: Path, tmp_path: Path) -> None:
    installation = make_installation(scratch, tests=dict(load_high_per_cpu=THRESHOLD))

    for conditions in flakes_under(scratch, tmp_path, installation, 0.5):
        assert conditions["load_high"] is False


def test_a_storms_conditions_have_the_cpu_count_and_the_loaded_flag(
    scratch: Path, tmp_path: Path
) -> None:
    installation = make_installation(
        scratch, tests=dict(load_high_per_cpu=THRESHOLD), global_limits=dict(max_flakes_per_run=2)
    )
    unit_test = build_unit_test(
        profile=cast(ToolchainProfile, BundleProfile()),
        run=BundleMachine(scratch, reruns=[0, 0]),
        changed=lambda *a: ["tests/test_one.py"],
        failures_dir=tmp_path / "bundles",
        installation=installation,
        machine=sampling(THRESHOLD * CPUS),
    )

    passed, _ = unit_test(cwd=scratch, base="main")

    assert passed
    (storm,) = storms(installation)
    assert storm["conditions"]["cpus"] == CPUS
    assert storm["conditions"]["load_high"] is True
