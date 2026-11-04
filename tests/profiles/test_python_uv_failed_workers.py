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


def test_a_run_without_xdist_names_no_worker() -> None:
    assert PythonUvProfile().failed_workers(PLAIN) == {}
