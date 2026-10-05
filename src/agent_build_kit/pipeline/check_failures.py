"""Which check a failed tier 1 run was, from what it printed (spec: telemetry).

The metrics count a failure by its kind, never by its text, and three kinds
cover what a person acts on: the linter or formatter, the type checker, the
tests. The output of a repo's own hook runner can hold any of them, so the
tools' own names and output shapes decide, not the command that ran them.
"""

from __future__ import annotations

import re

TYPES = re.compile(
    r"pyrefly|mypy|pyright|\btsc\b|error TS\d+|^ERROR [a-z]+(?:-[a-z]+)+\b",
    re.IGNORECASE | re.MULTILINE,
)
TESTS = re.compile(
    r"pytest|vitest|jest|short test summary|AssertionError|=+ .*\b(?:failed|passed)\b",
    re.IGNORECASE,
)


def failed_check(output: str) -> str:
    """`types`, `test` or `lint`: what failed, by what it printed."""
    if TYPES.search(output):
        return "types"
    if TESTS.search(output):
        return "test"
    return "lint"
