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
from agent_build_kit.pipeline.run_log import (
    TestRun,
    append_test_run,
    read_test_runs,
    rotated_ledger_path,
    run_ledger_path,
)
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.wiring import build_unit_test
from agent_build_kit.profiles.base import ToolchainProfile
from tests.e2e_base_fakes import branch
from tests.factories import stored_unit
from tests.failure_bundle_fakes import (
    RECORDED,
    START,
    BundleMachine,
    BundleProfile,
)
from tests.failure_bundle_fakes import run_ledger_rows as _rows
from tests.pipeline.test_flake_isolation import HookedProfile
from tests.pipeline.test_unit_test_affected import CHANGED, FAILED_OUTPUT
from tests.pipeline.test_unit_test_affected import Commands as SelectingCommands
from tests.pipeline.test_unit_test_affected import Profile as SelectingProfile
from tests.pipeline.test_unit_test_affected import repo_config as selecting_repo_config
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


def test_the_ledger_is_a_jsonl_file_of_the_state_directory(tmp_path: Path) -> None:
    assert run_ledger_path(tmp_path) == tmp_path / "test-runs.jsonl"


def test_a_row_is_a_line_appended_after_the_others(tmp_path: Path) -> None:
    path = run_ledger_path(tmp_path)

    append_test_run(path, _entry("add-marker/1"))
    append_test_run(path, _entry("add-marker/2"))

    assert [row["unit"] for row in _rows(path)] == ["add-marker/1", "add-marker/2"]


def test_a_ledger_at_its_size_limit_is_rotated_before_the_next_row(tmp_path: Path) -> None:
    path = run_ledger_path(tmp_path)
    # A short row is a little over 500 bytes (it carries the memory fields even when null), so
    # the limit leaves room for one of them.
    append_test_run(path, _entry("old/1"), max_bytes=800)
    append_test_run(path, _entry("old/2", failed=["x" * 600]), max_bytes=800)

    append_test_run(path, _entry("new/1"), max_bytes=800)

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


def test_the_rows_read_are_the_rotated_ledgers_then_the_current_ones_skipping_a_bad_line(
    tmp_path: Path,
) -> None:
    path = run_ledger_path(tmp_path)
    append_test_run(rotated_ledger_path(path), _entry("old/1"))
    append_test_run(path, _entry("new/1"))
    with path.open("a", encoding="utf-8") as handle:
        handle.write("not a row\n")
    append_test_run(path, _entry("new/2"))

    assert [row.unit for row in read_test_runs(tmp_path)] == ["old/1", "new/1", "new/2"]


def test_the_rows_read_of_a_state_directory_with_no_ledger_are_none(tmp_path: Path) -> None:
    assert read_test_runs(tmp_path) == []


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
    samples: tuple[dict[str, object], dict[str, object]] | None = None,
) -> tuple[bool, str] | None:
    """The unit-test run, its ledger at `ledger`; None when it found a flake. `samples`, when
    given, is the (start, end) machine sample: the first call answers the start, every later
    one the end."""
    loads = iter(range(1, 100))
    taken = iter(range(100))

    def sampled() -> dict[str, object]:
        if samples is None:
            return {"load": [float(next(loads))] * 3}
        return samples[0] if next(taken) == 0 else samples[1]

    clock = iter(START + timedelta(seconds=10 * n) for n in range(100))
    unit_test = build_unit_test(
        profile=cast(ToolchainProfile, BundleProfile()),
        run=machine,
        changed=lambda *a: ["tests/test_one.py"],
        failures_dir=ledger.parent / "bundles",
        test_runs=ledger,
        installation=installation,
        now=lambda: next(clock),
        machine=sampled,
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


_MEMORY_FIELDS = [
    "mem_available_mb_start",
    "mem_available_mb_end",
    "swap_used_mb_start",
    "swap_used_mb_end",
    "memory_pressure_full_us",
]


def _memory_sample(available_kb: int, swap_kb: int, pressure_us: int | None) -> dict[str, object]:
    sample: dict[str, object] = {
        "load": [1.0] * 3,
        "cpus": 4,
        "memory_available_kb": available_kb,
        "swap_used_kb": swap_kb,
    }
    if pressure_us is not None:
        sample["memory_pressure_full_us"] = pressure_us
    return sample


@pytest.mark.parametrize(
    ("reruns", "passing"),
    [([], True), ([1, 1], False), ([0, 0], False)],
    ids=["passing", "failing", "flaky"],
)
def test_a_run_of_any_outcome_has_its_memory_figures_in_whole_mb(
    scratch: Path, tmp_path: Path, reruns: list[int], passing: bool
) -> None:
    ledger = tmp_path / "test-runs.jsonl"
    samples = (
        _memory_sample(8 * 1024 * 1024 + 1023, 2 * 1024 * 1024, 1_000),
        _memory_sample(6 * 1024 * 1024, 3 * 1024 * 1024 + 5, 4_500),
    )

    _run(scratch, BundleMachine(scratch, reruns=reruns, passing=passing), ledger, samples=samples)

    (row,) = _rows(ledger)
    assert row.get("mem_available_mb_start", "absent") == 8 * 1024
    assert row.get("mem_available_mb_end", "absent") == 6 * 1024
    assert row.get("swap_used_mb_start", "absent") == 2 * 1024
    assert row.get("swap_used_mb_end", "absent") == 3 * 1024
    assert row.get("memory_pressure_full_us", "absent") == 3_500


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (_memory_sample(1024, 0, None), _memory_sample(1024, 0, 9)),
        (_memory_sample(1024, 0, 9), _memory_sample(1024, 0, None)),
        (_memory_sample(1024, 0, 50), _memory_sample(1024, 0, 9)),
    ],
    ids=["pressure only at end", "pressure only at start", "counter went back"],
)
def test_a_missing_reading_or_a_backwards_pressure_counter_gives_null_pressure(
    scratch: Path, tmp_path: Path, start: dict[str, object], end: dict[str, object]
) -> None:
    ledger = tmp_path / "test-runs.jsonl"

    _run(
        scratch,
        BundleMachine(scratch, reruns=[], passing=True),
        ledger,
        samples=(start, end),
    )

    (row,) = _rows(ledger)
    assert row.get("memory_pressure_full_us", "absent") is None


def test_samples_without_the_readings_give_null_for_each_memory_field(
    scratch: Path, tmp_path: Path
) -> None:
    ledger = tmp_path / "test-runs.jsonl"
    bare: dict[str, object] = {"load": [1.0] * 3}

    _run(scratch, BundleMachine(scratch, reruns=[], passing=True), ledger, samples=(bare, bare))

    (row,) = _rows(ledger)
    assert {name: row.get(name, "absent") for name in _MEMORY_FIELDS} == dict.fromkeys(
        _MEMORY_FIELDS
    )


_LINE_BEFORE_THE_FIELDS = {
    "unit": "old/1",
    "started": START.isoformat(),
    "seconds": 1.0,
    "outcome": "passed",
    "failed": [],
    "load_start": None,
    "load_end": None,
    "workers": None,
    "tick": "t1",
    "units_running": [],
}


def test_a_row_written_before_the_memory_fields_loads_with_each_of_them_null() -> None:
    row = TestRun.model_validate_json(json.dumps(_LINE_BEFORE_THE_FIELDS))

    assert {name: getattr(row, name, "absent") for name in _MEMORY_FIELDS} == dict.fromkeys(
        _MEMORY_FIELDS
    )


def _fix_round_row(
    tmp_path: Path,
    profile: SelectingProfile,
    commands: SelectingCommands,
    *,
    whole_repo: bool = False,
) -> dict[str, object]:
    """The one row of a fix round's unit-test run (so one with a failed check to answer, the
    only run a profile's selection is asked for) at a ledger in `tmp_path`."""
    ledger = tmp_path / "test-runs.jsonl"
    unit_test = build_unit_test(
        run=commands,
        changed=lambda *a: CHANGED,
        profile=profile,
        repo=selecting_repo_config(tmp_path),
        test_runs=ledger,
    )

    unit_test(cwd=tmp_path, base="main", failed_output=FAILED_OUTPUT, whole_repo=whole_repo)

    (row,) = _rows(ledger)
    return row


def test_a_run_of_a_selection_has_full_false(tmp_path: Path) -> None:
    row = _fix_round_row(
        tmp_path, SelectingProfile([["selected"]]), SelectingCommands(selected=(1, "FAILED"))
    )

    assert row.get("full", "absent") is False


@pytest.mark.parametrize(
    ("profile", "whole_repo"),
    [
        (SelectingProfile(None), False),
        (SelectingProfile([["selected"]]), True),
    ],
    ids=["the profile cannot name the affected tests", "a whole-repository run"],
)
def test_a_run_of_the_whole_suite_has_full_true(
    tmp_path: Path, profile: SelectingProfile, whole_repo: bool
) -> None:
    row = _fix_round_row(tmp_path, profile, SelectingCommands(), whole_repo=whole_repo)

    assert row.get("full", "absent") is True


@pytest.mark.parametrize(
    ("reruns", "passing"),
    [([], True), ([1, 1], False), ([0, 0], False)],
    ids=["passing", "failing", "flaky"],
)
def test_a_whole_suite_run_of_any_outcome_has_full_true(
    scratch: Path, tmp_path: Path, reruns: list[int], passing: bool
) -> None:
    ledger = tmp_path / "test-runs.jsonl"

    _run(scratch, BundleMachine(scratch, reruns=reruns, passing=passing), ledger)

    (row,) = _rows(ledger)
    assert row.get("full", "absent") is True


def test_a_row_written_before_the_full_field_loads_with_it_null() -> None:
    row = TestRun.model_validate_json(json.dumps(_LINE_BEFORE_THE_FIELDS))

    assert getattr(row, "full", "absent") is None


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


def test_a_row_records_the_head_and_the_base_the_run_saw(tmp_path: Path) -> None:
    repo, base = branch(tmp_path, {})
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()
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
    assert row["head"] == head
    assert row["base"] == base


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
