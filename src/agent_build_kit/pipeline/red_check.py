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

import logging
import re
from typing import Literal
from xml.etree import ElementTree

from agent_build_kit.model import Frozen

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


class RedResult(Frozen):
    """The verdict on a tests commit's run, and the failing tests it names."""

    verdict: Literal["accepted", "rejected"]
    tests: tuple[str, ...] = ()
    problems: tuple[str, ...] = ()


REPORT_MARK = "--- abk junit report ---"

LOG = logging.getLogger(__name__)


def split_report(output: str) -> tuple[str | None, str]:
    """The JUnit report a red command printed after `REPORT_MARK`, or None when
    it printed none, and the console output before it."""
    console, found, report = output.partition(REPORT_MARK)
    return (report.strip() or None, console) if found else (None, output)


def red_check(report: str) -> RedResult:
    """Judge a run from pytest's JUnit report, by each failing test's exception.

    Raises `ValueError` when `report` is not a JUnit report.
    """
    body = report.strip()
    if body.startswith("<!--"):
        body = body.partition("-->")[2].strip()
    try:
        root = ElementTree.fromstring(body)
    except ElementTree.ParseError as error:
        raise ValueError(f"not a JUnit report: {error}") from error

    failing: list[str] = []
    problems: list[str] = []
    passed = 0
    for case in root.iter("testcase"):
        name = "::".join(part for part in (case.get("classname"), case.get("name")) if part)
        bad = [*case.findall("failure"), *case.findall("error")]
        if not bad:
            passed += case.find("skipped") is None
            continue
        failing.append(name)
        for element in bad:
            said = f"{element.get('message') or ''}\n{element.text or ''}"
            if element.tag == "error":
                problems.append(f"{name}: {_error_reason(element, said)}")
            elif reasons := [why for marker, why in REJECTED.items() if marker in said]:
                problems.extend(f"{name}: {why}" for why in reasons)
            elif not any(marker in said for marker in ACCEPTED):
                problems.append(
                    f"{name}: the failure is not one we recognise as "
                    "'the behaviour isn't there yet'"
                )

    if passed:
        problems.append(
            f"{passed} test(s) passed at the tests commit — a test that passes "
            "before its implementation exists is not testing that implementation"
        )
    if not failing:
        problems.append("nothing failed at the tests commit")
    return RedResult(
        verdict="rejected" if problems else "accepted",
        tests=tuple(failing),
        problems=tuple(problems),
    )


def _error_reason(element: ElementTree.Element, said: str) -> str:
    if element.get("message") == "collection failure":
        return "the test module could not be collected, so no test failed for the missing behaviour"
    for marker, why in REJECTED.items():
        if marker in said:
            return why
    return "an error outside the test body is not a missing implementation"


def judge_red(report: str | None, output: str, exit_code: int) -> RedResult:
    """Judge a run from its `report`, or from the console `output` (logging
    that it did) when the report could not be written."""
    if report:
        try:
            return red_check(report)
        except ValueError as error:
            reason = str(error)
    else:
        reason = "no report was written"
    LOG.warning("red check: %s; using the console fallback", reason)
    ok, problems = interpret_pytest(output, exit_code=exit_code)
    return RedResult(verdict="accepted" if ok else "rejected", problems=tuple(problems))
