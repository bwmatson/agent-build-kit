"""Every unit-test run is a row of `runs/test-runs.jsonl` (spec: test-failure-evidence).

The ledger writer is exercised directly for its rotation, and through `build_unit_test` for the
row a passing, failing or flaky run adds. The runner answers as in `tests/failure_bundle_fakes.py`.
"""

from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from agent_build_kit import profiles
from agent_build_kit.config import ProjectConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.flakes import FailedOnBase, FlakeFound
from agent_build_kit.pipeline.run_log import TestRun, append_test_run, run_ledger_path
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.e2e_base_fakes import branch
from tests.factories import stored_unit
from tests.failure_bundle_fakes import RECORDED, START, BundleMachine, BundleProfile
from tests.pipeline.test_flake_isolation import HookedProfile
from tests.pipeline.test_unit_test_base_check import TEST, Runs

# --- the writer ---------------------------------------------------------------------


def _entry(unit: str, *, failed: list[str] | None = None) -> TestRun:
    return TestRun(
        unit=unit,
        started=START.isoformat(),
        seconds=1.0,
        outcome="passed",
        failed=failed or [],
        load_start=None,
        load_end=None,
        workers=None,
        tick="t1",
        units_running=[],
    )


def _rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_the_ledger_is_a_jsonl_file_of_the_state_directory(tmp_path: Path) -> None:
    assert run_ledger_path(tmp_path) == tmp_path / "test-runs.jsonl"


def test_a_row_is_a_line_appended_after_the_others(tmp_path: Path) -> None:
    path = run_ledger_path(tmp_path)

    append_test_run(path, _entry("add-marker/1"))
    append_test_run(path, _entry("add-marker/2"))

    assert [row["unit"] for row in _rows(path)] == ["add-marker/1", "add-marker/2"]


def test_a_ledger_at_its_size_limit_is_rotated_before_the_next_row(tmp_path: Path) -> None:
    path = run_ledger_path(tmp_path)
    append_test_run(path, _entry("old/1"), max_bytes=300)
    append_test_run(path, _entry("old/2", failed=["x" * 400]), max_bytes=300)

    append_test_run(path, _entry("new/1"), max_bytes=300)

    assert [row["unit"] for row in _rows(path)] == ["new/1"]
    rotated = path.with_name(path.name + ".1")
    assert [row["unit"] for row in _rows(rotated)] == ["old/1", "old/2"]


def test_a_second_rotation_replaces_the_first_one_so_the_ledger_stays_bounded(
    tmp_path: Path,
) -> None:
    path = run_ledger_path(tmp_path)
    for n in range(6):
        append_test_run(path, _entry(f"u/{n}", failed=["x" * 400]), max_bytes=300)

    assert sorted(child.name for child in tmp_path.iterdir() if child.suffix != ".lock") == [
        "test-runs.jsonl",
        "test-runs.jsonl.1",
    ]
    assert [row["unit"] for row in _rows(path)] == ["u/5"]
    assert [row["unit"] for row in _rows(path.with_name(path.name + ".1"))] == ["u/4"]


def test_a_ledger_under_its_limit_is_not_rotated(tmp_path: Path) -> None:
    path = run_ledger_path(tmp_path)

    for n in range(4):
        append_test_run(path, _entry(f"u/{n}"))

    assert not path.with_name(path.name + ".1").exists()
    assert len(_rows(path)) == 4


# --- a unit-test run ----------------------------------------------------------------


def _run(
    scratch: Path,
    machine: BundleMachine,
    ledger: Path,
    installation: Installation | None = None,
) -> tuple[bool, str] | None:
    """The unit-test run, its ledger at `ledger`; None when it found a flake."""
    loads = iter(range(1, 100))
    clock = iter(START + timedelta(seconds=10 * n) for n in range(100))
    unit_test = build_unit_test(
        profile=cast(ToolchainProfile, BundleProfile()),
        run=machine,
        changed=lambda *a: ["tests/test_one.py"],
        failures_dir=ledger.parent / "bundles",
        test_runs=ledger,
        installation=installation,
        now=lambda: next(clock),
        machine=lambda: {"load": [float(next(loads))] * 3},
    )
    try:
        return unit_test(cwd=scratch, base="main")
    except FlakeFound:
        return None


def test_a_passing_run_adds_a_row_with_the_outcome_passed_and_no_output(
    scratch: Path, tmp_path: Path
) -> None:
    ledger = tmp_path / "test-runs.jsonl"

    _run(scratch, BundleMachine(scratch, reruns=[], passing=True), ledger)

    (row,) = _rows(ledger)
    assert row["unit"] == "add-marker/1"
    assert row["outcome"] == "passed"
    assert row["failed"] == []
    assert not (tmp_path / "bundles").exists(), "a pass keeps no bundle, only the row"
    assert "passed in" not in json.dumps(row), "no output"
    assert not {"output", "stdout", "stderr"} & row.keys()


def test_a_row_names_the_start_the_seconds_the_workers_the_tick_and_the_units_running(
    scratch: Path, tmp_path: Path
) -> None:
    ledger = tmp_path / "test-runs.jsonl"

    _run(scratch, BundleMachine(scratch, reruns=[], passing=True), ledger)

    (row,) = _rows(ledger)
    assert row["started"] == START.isoformat()
    assert row["seconds"] > 0
    assert row["workers"] == "auto", "the profile's `-n` setting, as the bundle's context has it"
    assert row["tick"] == spans.PROCESS_TICK
    assert row["units_running"] == []


def test_a_row_has_the_load_at_the_start_and_at_the_end(scratch: Path, tmp_path: Path) -> None:
    ledger = tmp_path / "test-runs.jsonl"

    _run(scratch, BundleMachine(scratch, reruns=[], passing=True), ledger)

    (row,) = _rows(ledger)
    assert row["load_start"] == 1.0
    assert row["load_end"] > row["load_start"]


def test_a_failing_run_adds_a_row_naming_the_tests_that_failed(
    scratch: Path, tmp_path: Path
) -> None:
    ledger = tmp_path / "test-runs.jsonl"

    _run(scratch, BundleMachine(scratch, reruns=[1, 1]), ledger)

    (row,) = _rows(ledger)
    assert row["outcome"] == "failed"
    assert "test_one.py::test_plain" in row["failed"]
    assert "test_two.py::test_other" in row["failed"]
    assert not {"output", "stdout", "stderr"} & row.keys()


def test_a_run_that_found_a_flake_adds_a_row_too(scratch: Path, tmp_path: Path) -> None:
    ledger = tmp_path / "test-runs.jsonl"

    assert _run(scratch, BundleMachine(scratch, reruns=[0, 0]), ledger) is None

    (row,) = _rows(ledger)
    assert row["outcome"] == "flake"
    assert "test_one.py::test_plain" in row["failed"]


def test_each_run_adds_its_own_row(scratch: Path, tmp_path: Path) -> None:
    ledger = tmp_path / "test-runs.jsonl"

    _run(scratch, BundleMachine(scratch, reruns=[1, 1]), ledger)
    _run(scratch, BundleMachine(scratch, reruns=[], passing=True), ledger)

    assert [row["outcome"] for row in _rows(ledger)] == ["failed", "passed"]


def test_a_run_that_failed_on_the_base_adds_a_row_naming_the_test(tmp_path: Path) -> None:
    repo, base = branch(tmp_path, {})
    ledger = tmp_path / "test-runs.jsonl"
    unit_test = build_unit_test(
        profile=cast(ToolchainProfile, HookedProfile()),
        run=Runs(repo),
        changed=lambda *a: ["src/app.py"],
        test_runs=ledger,
    )

    with pytest.raises(FailedOnBase):
        unit_test(cwd=repo, base=base)

    (row,) = _rows(ledger)
    assert row["outcome"] == "failed"
    assert row["failed"] == [TEST]


def test_units_running_holds_the_ids_of_the_running_units_of_the_store_and_no_other(
    scratch: Path, tmp_path: Path, workspace: Installation
) -> None:
    UnitStore(workspace.state_dir / "units.json").upsert(
        [
            stored_unit("busy/1", change="busy", state="running"),
            stored_unit("done/1", change="done", state="merged"),
        ]
    )
    ledger = tmp_path / "test-runs.jsonl"

    _run(scratch, BundleMachine(scratch, reruns=[], passing=True), ledger, workspace)

    (row,) = _rows(ledger)
    assert row["units_running"] == ["busy/1"]


def test_a_ledger_that_cannot_be_written_does_not_change_the_runs_result(
    scratch: Path, tmp_path: Path
) -> None:
    (tmp_path / "in-the-way").write_text("a file where the ledger's folder should be")
    ledger = tmp_path / "in-the-way" / "test-runs.jsonl"

    result = _run(scratch, BundleMachine(scratch, reruns=[], passing=True), ledger)

    assert result == (True, "")


class ProjectMachine:
    """Every command passes but the test run, which fails as a recorded pytest run does."""

    def __call__(self, command: list[str], **kwargs: object) -> subprocess.CompletedProcess:
        if "pytest" not in " ".join(command):
            return subprocess.CompletedProcess(command, 0, "", "")
        failure = (RECORDED / "console_failures.txt").read_text().split("\n", 1)[1]
        return subprocess.CompletedProcess(command, 1, failure, "")


def test_the_failed_tests_are_read_by_the_profile_of_the_project_that_ran_them(
    tmp_path: Path,
) -> None:
    """The repo's profile (a node one) cannot read pytest's output; the project's can."""
    (tmp_path / "svc" / "tests").mkdir(parents=True)
    (tmp_path / "svc" / "pyproject.toml").write_text(
        '[project]\nname = "svc"\nversion = "0"\ndependencies = ["pytest-xdist"]\n'
    )
    ledger = tmp_path / "test-runs.jsonl"
    unit_test = build_unit_test(
        profile=profiles.get("node-npm"),
        projects=[ProjectConfig(path="svc", profile="python-uv")],
        run=ProjectMachine(),
        changed=lambda *a: ["svc/tests/test_one.py"],
        test_runs=ledger,
    )

    passed, _ = unit_test(cwd=tmp_path, base="main")

    assert not passed
    (row,) = _rows(ledger)
    assert row["outcome"] == "failed"
    assert "test_one.py::test_plain" in row["failed"]
    assert "test_two.py::test_other" in row["failed"]
