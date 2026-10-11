"""The context report: per step kind the mean and 90th percentile of what a call added, the
compactions and the end fill as used over max; per session the fill after each step; the steps
that add the most; rows with no context counted as unknown (spec: usage-reporting, The report
shows context use per step and per session).

The ledger's lines are the input.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.usage_report import (
    ContextReport,
    build_context_report,
    render_context,
)
from tests.factories import stored_unit
from tests.ledger_lines import agent_line, context_line, write_ledger

K = 1000
UNITS = [stored_unit("add-marker/1", repo="app")]


def report_of(tmp_path: Path, *lines: dict) -> ContextReport:
    ledger = write_ledger(tmp_path / "state" / "usage-ledger.jsonl", *lines)
    return build_context_report(ledger, UNITS)


def at(minute: int, **fields) -> dict:
    return {"at": f"2026-01-01T10:{minute:02d}:00+00:00"} | fields


def step_of(report: ContextReport, node: str):
    (step,) = [s for s in report.steps if s.node == node]
    return step


def test_a_step_kinds_added_context_is_summarised_by_its_mean_and_90th_percentile(
    tmp_path: Path,
) -> None:
    added = [1, 2, 3, 4, 5, 6, 7, 8, 10, 10]
    lines = [
        context_line(
            50 * K,
            (50 + n) * K,
            node="rework",
            round=i,
            session_id=f"sess-{i}",
            **at(i),
        )
        for i, n in enumerate(added)
    ]

    step = step_of(report_of(tmp_path, *lines), "rework")

    assert step.calls == 10
    assert step.mean_added == pytest.approx(5.6 * K)
    assert step.p90_added == pytest.approx(10 * K)


def test_the_end_fill_reads_as_used_over_max(tmp_path: Path) -> None:
    report = report_of(
        tmp_path, context_line(100 * K, 142 * K, node="implement", window=200 * K, **at(0))
    )

    step = step_of(report, "implement")
    assert (step.used_end, step.max) == (142 * K, 200 * K)
    assert "142k / 200k" in render_context(report)


def test_a_peak_is_shown_only_where_it_differs_from_the_end_fill(tmp_path: Path) -> None:
    report = report_of(
        tmp_path,
        context_line(
            150 * K,
            80 * K,
            peak=195 * K,
            compactions=1,
            node="rework",
            session_id="a",
            **at(0),
        ),
        context_line(50 * K, 70 * K, node="review", session_id="b", **at(1)),
    )

    assert step_of(report, "rework").peak == 195 * K
    assert step_of(report, "review").peak is None
    shown = {
        node: next(line for line in render_context(report).splitlines() if node in line)
        for node in ("rework", "review")
    }
    assert "195k" in shown["rework"]
    assert "195k" not in shown["review"]
    assert step_of(report, "rework").compactions == 1


def test_a_sessions_rows_show_the_fill_after_each_step_in_order(tmp_path: Path) -> None:
    steps = [("tests", 50), ("implement", 70), ("rework", 90), ("review", 120)]
    lines = [
        context_line(
            (fill - 20) * K,
            fill * K,
            node=node,
            session_id="sess-worked",
            **at(i),
        )
        for i, (node, fill) in enumerate(steps)
    ]

    report = report_of(tmp_path, *reversed(lines))

    (session,) = report.sessions
    assert session.session_id == "sess-worked"
    assert session.fills == (50 * K, 70 * K, 90 * K, 120 * K)


def test_the_steps_that_add_the_most_are_listed_largest_first(tmp_path: Path) -> None:
    report = report_of(
        tmp_path,
        context_line(10 * K, 20 * K, node="tests", session_id="a", **at(0)),
        context_line(20 * K, 80 * K, node="implement", session_id="a", **at(1)),
        context_line(80 * K, 110 * K, node="rework", session_id="a", **at(2)),
    )

    assert [(a.node, a.added) for a in report.biggest] == [
        ("implement", 60 * K),
        ("rework", 30 * K),
        ("tests", 10 * K),
    ]
    assert report.biggest[0].unit == "add-marker/1"


def test_rows_with_no_context_are_counted_as_unknown_and_left_out_of_the_means(
    tmp_path: Path,
) -> None:
    report = report_of(
        tmp_path,
        agent_line(node="implement", round=0, session_id="old-1", **at(0)),
        agent_line(node="implement", round=1, session_id="old-2", **at(1)),
        context_line(None, None, window=None, basis="unknown", node="implement", round=2, **at(2)),
        context_line(100 * K, 140 * K, node="implement", round=3, session_id="new", **at(3)),
    )

    step = step_of(report, "implement")
    assert report.unknown_calls == 3
    assert step.calls == 1
    assert step.mean_added == pytest.approx(40 * K)
    assert "3 unknown" in render_context(report)


def test_a_ledger_with_no_context_at_all_reports_only_the_unknown_count(tmp_path: Path) -> None:
    report = report_of(tmp_path, agent_line(**at(0)))

    assert report.steps == ()
    assert report.sessions == ()
    assert report.biggest == ()
    assert report.unknown_calls == 1
