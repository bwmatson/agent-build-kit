"""Did the tests commit fail, and fail for a reason that counts?

Tests-first only means something if the tests were run at the tests commit and
lost there. This module reads a pytest run from that commit and decides
whether it was honestly red (docs/architecture.md).

"Red" is deliberately narrower than "non-zero exit code":

- **A passing test is not red.** If it passed before the implementation
  existed, it is not testing that implementation. This is the case the whole
  check exists for.
- **Nothing collected is not red.** An empty run exits non-zero and asserts
  nothing — the quietest possible way to fake the evidence.
- **A syntax error or a missing fixture is not red.** They fail for reasons
  unrelated to the missing behaviour, and would keep failing afterwards.
- **An assertion failure, `NotImplementedError`, or a missing module or
  attribute *is* red.** Those are what a real test looks like before its
  implementation lands — with or without stubs in the commit.

Anything unrecognised is not red either. Certifying a run we can't read would
defeat the point.
"""

from __future__ import annotations

import re

# "1 failed, 2 passed in 0.06s" / "3 passed in 0.10s"
COUNT = re.compile(r"(\d+) (passed|failed|error|errors|skipped)")
NO_TESTS = re.compile(r"no tests ran|collected 0 items", re.IGNORECASE)

# Failures that mean "the behaviour isn't there yet", which is the point.
ACCEPTED = (
    "AssertionError",
    "NotImplementedError",
    "ModuleNotFoundError",
    "ImportError",
    "AttributeError",
    "assert ",
)

# Failures that mean "this test is broken", which is a different problem and
# would not be fixed by the implementation landing.
REJECTED = {
    "SyntaxError": "a syntax error is not a missing implementation",
    "IndentationError": "an indentation error is not a missing implementation",
    "fixture": "a missing or broken fixture fails for its own reasons",
    "ConftestImportFailure": "a broken conftest fails for its own reasons",
}


def _counts(output: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for number, label in COUNT.findall(output):
        label = "error" if label.startswith("error") else label
        counts[label] = counts.get(label, 0) + int(number)
    return counts


def interpret_pytest(output: str, *, exit_code: int) -> tuple[bool, list[str]]:
    """Was this run honestly red? Returns (ok, problems).

    `problems` is empty when ok, and otherwise says what disqualified the run,
    so the message a developer sees names the actual rule.
    """
    problems: list[str] = []
    counts = _counts(output)

    if NO_TESTS.search(output) or (not counts and exit_code != 0):
        return False, [
            "no tests ran at the tests commit, so nothing was shown to fail "
            f"(exit code {exit_code})"
        ]

    if counts.get("passed"):
        problems.append(
            f"{counts['passed']} test(s) passed at the tests commit — a test that passes "
            "before its implementation exists is not testing that implementation"
        )

    failures = counts.get("failed", 0) + counts.get("error", 0)
    if not failures:
        problems.append("nothing failed at the tests commit")
        return False, problems

    for marker, why in REJECTED.items():
        if marker in output:
            problems.append(f"{marker}: {why}")

    if not any(marker in output for marker in ACCEPTED):
        problems.append(
            "the failure is not one we recognise as 'the behaviour isn't there yet' "
            "(expected an assertion failure, NotImplementedError, or a missing "
            "module/attribute)"
        )

    return not problems, problems
