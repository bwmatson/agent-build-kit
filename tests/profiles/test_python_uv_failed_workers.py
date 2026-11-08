"""The python-uv profile reads the worker of each failed test from a recorded xdist run
(`pytest -n 2 -q -rfE --tb=short`), where the `[gwN] ...` line heads the test's block (spec:
test-failure-evidence)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.profiles.python_uv import PythonUvProfile

RECORDED = Path(__file__).resolve().parents[1] / "fixtures" / "external" / "pytest"
XDIST = (RECORDED / "console_xdist_failures.txt").read_text()
PLAIN = (RECORDED / "console_failures.txt").read_text()


def test_each_failed_test_maps_to_the_worker_that_ran_it() -> None:
    workers = PythonUvProfile().failed_workers(XDIST)

    assert workers == {
        "test_one.py::test_plain": "gw0",
        "test_one.py::TestGroup::test_method": "gw1",
        "test_one.py::test_cases[2]": "gw0",
        "test_two.py::test_other": "gw1",
        "test_one.py::test_setup_error": "gw0",
    }


def test_the_recorded_summary_order_gives_no_consequences_without_progress_lines() -> None:
    # The summary lists every FAILED line before every ERROR line, so it says nothing of time.
    assert PythonUvProfile().consequence_errors(XDIST) == []


def test_a_recorded_verbose_run_gives_the_error_after_the_hit_and_not_the_one_before() -> None:
    recorded = (RECORDED / "console_xdist_verbose_timeout.txt").read_text()

    assert PythonUvProfile().consequence_errors(recorded) == ["test_one.py::test_after"]


def test_only_errors_after_the_first_hit_of_their_worker_are_consequences() -> None:
    output = (
        "[gw0] [ 10%] ERROR tests/a.py::test_before\n"
        "[gw1] [ 20%] ERROR tests/a.py::test_other_worker\n"
        "[gw0] [ 30%] FAILED tests/a.py::test_slow\n"
        "[gw0] [ 40%] ERROR tests/a.py::test_after\n"
        "=== short test summary info ===\n"
        "FAILED tests/a.py::test_slow - Failed: Timeout >60.0s\n"
        "ERROR tests/a.py::test_before - RuntimeError: no db\n"
        "ERROR tests/a.py::test_other_worker - RuntimeError: no db\n"
        "ERROR tests/a.py::test_after - RuntimeError: no db\n"
    )

    assert PythonUvProfile().consequence_errors(output) == ["tests/a.py::test_after"]


def test_a_run_without_xdist_names_no_worker() -> None:
    assert PythonUvProfile().failed_workers(PLAIN) == {}
