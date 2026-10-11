"""What a run replayed and what went live, per test and in total."""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterable

from agent_build_kit.model import Frozen
from agent_build_kit.replay.models import Rule


class Miss(Frozen):
    """A call that went live: its place in the test, its key, and where its request
    differs from the nearest earlier cassette for the same test and call index."""

    call_index: int
    key: str
    difference: str


class ReplayedTest(Frozen):
    test_id: str
    # The calls answered from a cassette.
    hits: int = 0
    misses: list[Miss] = []
    # The cassettes the test did not ask for, by path under the cassette directory.
    unused: list[str] = []
    # The keys of the cassettes that matched but were too old to answer.
    aged_out: list[str] = []
    rules: list[Rule] = []


class RunReport(Frozen):
    tests: list[ReplayedTest] = []
    rules: list[Rule] = []
    # The replayed calls whose recorded response carried usage figures, and those figures' total.
    billed_calls_avoided: int = 0
    tokens_avoided: int = 0


def replay_label(test: ReplayedTest) -> str | None:
    """`replayed: N of M external calls replayed, K live`, or None when nothing replayed."""
    if not test.hits:
        return None
    live = len(test.misses)
    return f"replayed: {test.hits} of {test.hits + live} external calls replayed, {live} live"


def combine(reports: Iterable[RunReport]) -> RunReport:
    """One report for the runs of several tests."""
    tests: list[ReplayedTest] = []
    rules: list[Rule] = []
    calls = tokens = 0
    for report in reports:
        tests += report.tests
        rules += [rule for rule in report.rules if rule not in rules]
        calls += report.billed_calls_avoided
        tokens += report.tokens_avoided
    return RunReport(tests=tests, rules=rules, billed_calls_avoided=calls, tokens_avoided=tokens)


def render(report: RunReport) -> list[str]:
    """The lines of the terminal summary: each test that replayed or went live, and the totals."""
    lines: list[str] = []
    for test in report.tests:
        label = replay_label(test)
        if label is None and not (test.misses or test.unused or test.aged_out):
            continue
        lines.append(f"{test.test_id}: {label or 'nothing replayed'}")
        lines += [f"  live: call {miss.call_index}: {miss.difference}" for miss in test.misses]
        lines += [f"  aged out: {key[:12]}" for key in test.aged_out]
        lines += [f"  unused: {name}" for name in test.unused]
        lines += [f"  rule: {rule.pattern!r} -> {rule.placeholder!r}" for rule in test.rules]
    if report.tests:
        hit = sum(test.hits for test in report.tests)
        live = sum(len(test.misses) for test in report.tests)
        unused = sum(len(test.unused) for test in report.tests)
        aged = sum(len(test.aged_out) for test in report.tests)
        lines.append(f"total: {hit} hit, {live} live, {unused} unused, {aged} aged out")
    lines += [f"rule used: {rule.pattern!r} -> {rule.placeholder!r}" for rule in report.rules]
    if report.billed_calls_avoided:
        lines.append(
            f"billed calls avoided: {report.billed_calls_avoided} ({report.tokens_avoided} tokens)"
        )
    return lines


def usage_tokens(headers: dict[str, str], chunks: list[bytes]) -> int | None:
    """The input and output tokens a recorded response reports, or None when it reports none.
    Reads a JSON body, or the `usage` objects of a stream's events."""
    body = b"".join(chunks)
    if headers.get("content-encoding") == "gzip":
        try:
            body = gzip.decompress(body)
        except (OSError, EOFError):
            return None
    figures: dict[str, int] = {}
    for payload in _payloads(body.decode(errors="replace")):
        if not isinstance(payload, dict):
            continue
        message = payload.get("message")
        for holder in (payload, message if isinstance(message, dict) else {}):
            usage = holder.get("usage")
            if isinstance(usage, dict):
                figures.update(
                    {
                        name: value
                        for name, value in usage.items()
                        if name in ("input_tokens", "output_tokens") and isinstance(value, int)
                    }
                )
    return sum(figures.values()) if figures else None


def _payloads(text: str) -> list[object]:
    try:
        return [json.loads(text)]
    except ValueError:
        pass
    found: list[object] = []
    for line in text.splitlines():
        if line.startswith("data:"):
            try:
                found.append(json.loads(line.removeprefix("data:")))
            except ValueError:
                continue
    return found
