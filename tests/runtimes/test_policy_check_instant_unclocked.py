"""The static check's "instant" test does not wait on the clock.

How fast a machine judges a few hundred entries depends on how loaded it is, so a test
that asserts an elapsed time fails under parallel load and passes alone. The test states
the speed as work done instead, which gives the same answer however loaded the machine is.
"""

from __future__ import annotations

import ast
from pathlib import Path

INSTANT = Path(__file__).with_name("test_policy_check_instant.py")
CLOCKS = frozenset({"perf_counter", "perf_counter_ns", "monotonic", "process_time", "time"})


def test_the_instant_check_test_reads_no_clock() -> None:
    tree = ast.parse(INSTANT.read_text())
    imported = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "time"
        for alias in node.names
        if alias.name in CLOCKS
    }
    reads = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
            if func.value.id == "time" and func.attr in CLOCKS:
                reads.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id in imported:
            reads.append(node.lineno)

    assert reads == []
