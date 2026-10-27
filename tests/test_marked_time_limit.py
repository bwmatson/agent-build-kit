"""A test can carry its own time limit (spec: ci-gives-npm-a-longer-timeout).

A test marked `time_limit(<seconds>)` is held to that many seconds in place of
`--test-time-limit`; other tests and the e2e limit are as before. The plugin is driven in
a child pytest over the files of `tests/child_modules/marked_time_limit/`. No outcome here
depends on how long anything takes: the child swaps `threading.Timer` for a recorder, so a
test reads the limit the hook armed, and where a test must run past its limit the recorder
fires the first timer of that test at once and the test blocks until the signal arrives.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from tests.child_pytest import run_scenario
from tests.tracked_files import ROOT, guarded_files

SCENARIO = "tests/child_modules/marked_time_limit"
CLOCK_CALLS = {"sleep", "monotonic", "perf_counter"}


def scenario_files() -> list[Path]:
    return guarded_files(root=ROOT, under=[SCENARIO], suffixes={".py"})


def clock_hits(path: Path) -> list[str]:
    """`path:line` of each import of `time` and each call of a sleep or a clock in `path`."""
    hits: list[str] = []
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import) and any(a.name == "time" for a in node.names):
            hits.append(f"{path}:{node.lineno}")
        elif isinstance(node, ast.ImportFrom) and node.module == "time":
            hits.append(f"{path}:{node.lineno}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            is_time_time = (
                isinstance(func, ast.Attribute)
                and func.attr == "time"
                and getattr(func.value, "id", "") == "time"
            )
            if name in CLOCK_CALLS or is_time_time:
                hits.append(f"{path}:{node.lineno}")
    return hits


def test_a_marked_test_runs_past_the_default_and_passes(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = run_scenario(
        pytester,
        "marked_time_limit",
        "reads_the_limit.py",
        "--test-time-limit=9000",
        "--e2e-test-time-limit=20",
        "-rA",
        monkeypatch=monkeypatch,
    ).output

    assert "PASSED reads_the_limit.py::test_marked_runs_past_the_default" in output, output
    assert "PASSED reads_the_limit.py::test_marked_runs_past_its_own_limit" in output, output
    assert "PASSED reads_the_limit.py::test_unmarked_beside_them" in output, output
    assert "exceeded" not in output, output


def test_a_marked_test_past_its_own_limit_fails_naming_that_limit(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = run_scenario(
        pytester,
        "marked_time_limit",
        "blocks.py",
        "--test-time-limit=20",
        "--e2e-test-time-limit=20",
        env={"CHILD_FIRE_FIRST_TIMER": "1"},
        monkeypatch=monkeypatch,
    ).output

    assert "FAILED blocks.py::test_marked_runs_past_its_own_limit" in output, output
    assert "test exceeded the time limit of 1 seconds" in output, output


def test_an_unmarked_test_beside_a_marked_one_still_fails_at_the_default(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = run_scenario(
        pytester,
        "marked_time_limit",
        "blocks.py",
        "--test-time-limit=20",
        "--e2e-test-time-limit=20",
        env={"CHILD_FIRE_FIRST_TIMER": "1"},
        monkeypatch=monkeypatch,
    ).output

    assert "FAILED blocks.py::test_unmarked_beside_them" in output, output
    assert "test exceeded the time limit of 20 seconds" in output, output
    assert "2 failed" in output, output


def test_the_scenario_files_hold_no_clock_or_sleep() -> None:
    files = scenario_files()

    assert {path.name for path in files} >= {"reads_the_limit.py", "blocks.py", "conftest.py"}
    assert [hit for path in files for hit in clock_hits(path)] == []


def test_the_clock_check_fails_a_file_that_reads_a_clock(tmp_path: Path) -> None:
    scenario = next(path for path in scenario_files() if path.name == "reads_the_limit.py")
    clocked = tmp_path / "clocked.py"
    clocked.write_text(scenario.read_text() + "\n\ndef reads_a_clock():\n    time.monotonic()\n")

    hits = clock_hits(clocked)

    assert hits == [f"{clocked}:{len(clocked.read_text().splitlines())}"]
