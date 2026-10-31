"""No test of how the ACP adapter ends a run bounds it by seconds.

A bound of wall-clock seconds around a run fails a loaded machine (twice in a full gate) and
adds nothing: `_run_bounded` already fails a run that does not return (spec:
acp-outcome-tests-do-not-time-the-run).
"""

from __future__ import annotations

import ast

from tests.tracked_files import ROOT

MODULE = ROOT / "tests" / "runtimes" / "test_acp_outcome.py"
CLOCK_NAME = "elapsed"


def names_in(node: ast.AST) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def functions_comparing_the_clock(source: str) -> list[str]:
    """The test functions with a comparison or assert that reads `elapsed`."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
            reads = [
                n
                for n in ast.walk(node)
                if isinstance(n, ast.Compare) and CLOCK_NAME in names_in(n)
            ]
            if reads:
                found.append(node.name)
    return sorted(found)


def test_no_test_of_the_outcome_compares_the_duration_of_a_run() -> None:
    assert functions_comparing_the_clock(MODULE.read_text()) == []


def test_the_scan_names_a_test_that_compares_the_duration() -> None:
    source = (
        "def test_slow():\n    elapsed = 1\n    assert elapsed < 5\n\n"
        "def test_fine():\n    assert 1\n"
    )

    assert functions_comparing_the_clock(source) == ["test_slow"]
