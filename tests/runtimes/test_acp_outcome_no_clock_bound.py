"""No test of how the ACP adapter ends a run bounds it by seconds.

A bound of wall-clock seconds around a run fails a loaded machine (twice in a full gate) and
adds nothing: `_run_bounded` already fails a run that does not return (spec:
acp-outcome-tests-do-not-time-the-run).
"""

from __future__ import annotations

import ast

import pytest

from tests.tracked_files import ROOT

MODULE = ROOT / "tests" / "runtimes" / "test_acp_outcome.py"
CLOCK_NAME = "elapsed"


CLOCKS = {"monotonic", "time", "perf_counter"}
TIMER = "_run_bounded"


def reads_a_clock(node: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Attribute)
        and n.attr in CLOCKS
        and isinstance(n.value, ast.Name)
        and n.value.id == "time"
        for n in ast.walk(node)
    )


def compares_the_duration(node: ast.AST) -> bool:
    return any(
        isinstance(n, ast.Compare)
        and any(isinstance(m, ast.Name) and m.id == CLOCK_NAME for m in ast.walk(n))
        for n in ast.walk(node)
    )


def keeps_the_duration(node: ast.AST) -> bool:
    """Whether the function binds the duration `_run_bounded` returns to a name, not to `_`."""
    for n in ast.walk(node):
        call = n.value if isinstance(n, ast.Assign) else None
        if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Name)):
            continue
        if call.func.id != TIMER:
            continue
        target = n.targets[0]  # type: ignore[attr-defined]
        if not isinstance(target, ast.Tuple) or len(target.elts) != 2:
            return True
        second = target.elts[1]
        if not (isinstance(second, ast.Name) and second.id == "_"):
            return True
    return False


def functions_comparing_the_clock(source: str) -> list[str]:
    """The functions, other than the one that times the run, that read the clock, compare
    `elapsed` or keep the duration the timer returns."""
    return sorted(
        node.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name != TIMER
        and (reads_a_clock(node) or compares_the_duration(node) or keeps_the_duration(node))
    )


def test_no_test_of_the_outcome_compares_the_duration_of_a_run() -> None:
    assert functions_comparing_the_clock(MODULE.read_text()) == []


SPELLINGS = {
    "a name for the duration": (
        "def test_a():\n    result, took = _run_bounded(request)\n    assert took < 5\n"
    ),
    "the clock read in the test": ("def test_a():\n    assert time.monotonic() - started < 5\n"),
    "the clock read as perf_counter": (
        "def test_a():\n    assert time.perf_counter() - started < 5\n"
    ),
    "a helper that is not a test": ("def check_fast(elapsed):\n    assert elapsed < 5\n"),
}


@pytest.mark.parametrize("source", SPELLINGS.values(), ids=SPELLINGS.keys())
def test_the_scan_names_other_spellings_of_a_clock_bound(source: str) -> None:
    assert functions_comparing_the_clock(source) != []


def test_the_scan_leaves_the_helper_that_times_the_run_alone() -> None:
    source = (
        "def _run_bounded(request):\n    started = time.monotonic()\n"
        "    return None, time.monotonic() - started\n\n"
        "def test_a():\n    result, _ = _run_bounded(request)\n    assert result\n"
    )

    assert functions_comparing_the_clock(source) == []


def test_the_scan_names_a_test_that_compares_the_duration() -> None:
    source = (
        "def test_slow():\n    elapsed = 1\n    assert elapsed < 5\n\n"
        "def test_fine():\n    assert 1\n"
    )

    assert functions_comparing_the_clock(source) == ["test_slow"]
