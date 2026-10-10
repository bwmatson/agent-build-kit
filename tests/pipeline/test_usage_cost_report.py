"""Every cost total is the sum of incremental figures; legacy rows are counted and shown
apart; a session that does not add up is flagged (spec: usage-reporting, Cost in every report,
summary and metric is the sum of incremental figures).

The ledger's lines are the input: the worked session of nine calls whose recorded totals
summed to several times its spend, as the ledger writes them now, and the older lines as
they were written before.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline.usage_report import (
    GROUPINGS,
    Report,
    ReportRow,
    build_report,
    render_json,
    render_table,
    roll_up_change,
)
from tests.factories import stored_unit
from tests.ledger_lines import costed_line, legacy_line, worked_session, write_ledger

UNITS = [
    stored_unit("add-marker/1", repo="app"),
    stored_unit("add-marker/2", repo="platform"),
]
TRUTH = 25.39


def row_of(report: Report, key: str) -> ReportRow:
    (row,) = [r for r in report.rows if r.key == key]
    return row


@pytest.fixture
def worked(tmp_path: Path) -> Path:
    return write_ledger(tmp_path / "state" / "usage-ledger.jsonl", *worked_session())


@pytest.mark.parametrize(
    ("group_by", "key"),
    [
        ("unit", "add-marker/1"),
        ("change", "add-marker"),
        ("repo", "app"),
        ("day", "2026-01-01"),
    ],
)
def test_a_groups_cost_equals_its_sessions_increments(
    worked: Path, group_by: str, key: str
) -> None:
    assert group_by in GROUPINGS

    report = build_report(worked, UNITS, group_by=group_by)

    assert row_of(report, key).measured.cost_usd == pytest.approx(TRUTH)
    assert report.total.measured.cost_usd == pytest.approx(TRUTH)


def test_a_units_cost_is_the_sum_of_its_calls_own_spends_not_of_their_running_totals(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        *[
            costed_line(own, total, session_id="s", node=node, at=f"2026-01-01T10:0{n}:00+00:00")
            for n, (node, own, total) in enumerate(
                [("tests", 2.63, 2.63), ("implement", 2.86, 5.49), ("review", 7.69, 13.18)]
            )
        ],
    )

    report = build_report(ledger, UNITS, group_by="unit")

    assert row_of(report, "add-marker/1").measured.cost_usd == pytest.approx(13.18)


def test_the_report_shows_each_sessions_final_cumulative_beside_its_increments(
    worked: Path,
) -> None:
    report = build_report(worked, UNITS, group_by="unit")

    (session,) = report.sessions
    assert session.session_id == "sess-worked"
    assert session.incremental_usd == pytest.approx(TRUTH)
    assert session.cumulative_usd == pytest.approx(TRUTH)
    assert session.flagged is False
    table = render_table(report)
    assert "cumulative" in table
    assert "sess-worked" in table


def test_a_session_whose_increments_do_not_add_up_is_flagged(tmp_path: Path) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        costed_line(1.0, 1.0, basis="first", session_id="short", node="tests"),
        costed_line(1.0, 5.0, session_id="short", node="implement", resumed=True),
        *[
            costed_line(own, total, session_id="whole", unit="add-marker/2", node=node)
            for node, own, total in [("tests", 1.0, 1.0), ("implement", 1.0, 2.0)]
        ],
    )

    report = build_report(ledger, UNITS, group_by="unit")

    flags = {s.session_id: s.flagged for s in report.sessions}
    assert flags == {"short": True, "whole": False}
    assert json.loads(render_json(report))["sessions"]


def test_a_call_with_basis_unknown_adds_nothing_and_is_counted_among_the_unknown(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        costed_line(2.0, 2.0, basis="first", session_id="a", node="tests"),
        costed_line(None, 9.0, basis="unknown", session_id="b", node="implement"),
    )

    report = build_report(ledger, UNITS, group_by="unit")

    assert report.total.measured.cost_usd == pytest.approx(2.0)
    assert report.total.measured.calls == 2
    assert report.unknown_calls == 1


# --- legacy rows ------------------------------------------------------------------------


def legacy_ledger(tmp_path: Path) -> Path:
    return write_ledger(
        tmp_path / "ledger.jsonl",
        legacy_line(5.49, node="tests", session_id="old-1", at="2026-01-01T09:00:00+00:00"),
        legacy_line(13.18, node="review", session_id="old-2", at="2026-01-01T09:30:00+00:00"),
        costed_line(2.0, 2.0, basis="first", node="implement", session_id="new"),
    )


def test_legacy_rows_are_counted_and_listed_and_their_total_is_kept_apart(
    tmp_path: Path,
) -> None:
    report = build_report(legacy_ledger(tmp_path), UNITS, group_by="unit")

    assert report.total.measured.cost_usd == pytest.approx(2.0), "never summed as incremental"
    assert row_of(report, "add-marker/1").measured.cost_usd == pytest.approx(2.0)
    assert report.legacy.count == 2
    assert report.legacy.total_usd == pytest.approx(18.67)
    assert sorted((r.node, r.legacy_usd) for r in report.legacy.rows) == [
        ("review", 13.18),
        ("tests", 5.49),
    ]


def test_the_legacy_total_is_on_a_line_of_its_own_in_the_table(tmp_path: Path) -> None:
    table = render_table(build_report(legacy_ledger(tmp_path), UNITS, group_by="unit"))

    (line,) = [x for x in table.splitlines() if "legacy" in x.lower() and "18.67" in x]
    assert "2.00" not in line, "apart from the cost total"


def test_a_ledger_with_no_legacy_rows_says_nothing_of_them(worked: Path) -> None:
    report = build_report(worked, UNITS, group_by="unit")

    assert report.legacy.count == 0
    assert report.legacy.total_usd is None
    assert [s.session_id for s in report.sessions] == ["sess-worked"]
    assert "legacy" not in render_table(report).lower()


# --- the summary written at archive -----------------------------------------------------


def test_the_summary_written_at_archive_sums_increments_and_its_breakdown_sums_to_its_totals(
    worked: Path,
) -> None:
    roll_up_change(worked, "add-marker")

    (summary,) = [json.loads(x) for x in worked.read_text().splitlines()]
    assert summary["kind"] == "summary"
    assert summary["measured"]["cost_usd"] == pytest.approx(TRUTH)
    items = summary["breakdown"]
    assert sum(i["measured"]["cost_usd"] or 0 for i in items) == pytest.approx(TRUTH)
    assert sum(i["measured"]["calls"] for i in items) == summary["measured"]["calls"]


def test_an_archived_unit_reports_the_same_cost_as_its_detail_did(worked: Path) -> None:
    before = build_report(worked, UNITS, group_by="unit").total.measured.cost_usd
    roll_up_change(worked, "add-marker")

    after = build_report(worked, UNITS, group_by="unit")

    assert before == pytest.approx(TRUTH)
    assert after.total.measured.cost_usd == pytest.approx(before)


def test_a_summary_keeps_legacy_figures_apart_from_its_cost_and_a_summary_with_no_breakdown_loads(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(
        tmp_path / "state" / "usage-ledger.jsonl",
        legacy_line(13.18, node="tests", session_id="old"),
        costed_line(2.0, 2.0, basis="first", node="implement", session_id="new"),
        {
            "kind": "summary",
            "at": "2025-12-01T10:00:00+00:00",
            "unit": "feature/1",
            "change": "feature",
            "repo": "app",
            "measured": {"calls": 3, "cost_usd": 4.5},
            "estimated": {"calls": 0},
        },
    )

    units = [*UNITS, stored_unit("feature/1", change="feature")]
    before = build_report(ledger, units, group_by="unit")

    roll_up_change(ledger, "add-marker")

    kinds = [json.loads(x) for x in ledger.read_text().splitlines()]
    (ours,) = [x for x in kinds if x["unit"] == "add-marker/1"]
    assert ours["measured"]["cost_usd"] == pytest.approx(2.0)
    report = build_report(ledger, units, group_by="unit")
    assert row_of(report, "feature/1").measured.cost_usd == 4.5
    assert before.legacy.total_usd == pytest.approx(13.18)
    assert report.legacy.total_usd == pytest.approx(13.18)
    assert report.legacy.count == before.legacy.count == 1
    assert [(r.unit, r.node) for r in report.legacy.rows] == [("add-marker/1", "tests")]
    assert row_of(report, "add-marker/1").measured.cost_usd == pytest.approx(2.0)
    assert report.total.measured.cost_usd == pytest.approx(2.0 + 4.5)


def test_rolling_up_again_keeps_the_legacy_figures_of_the_earlier_summary(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(
        tmp_path / "state" / "usage-ledger.jsonl",
        legacy_line(13.18, node="tests", session_id="old"),
    )
    roll_up_change(ledger, "add-marker")
    with ledger.open("a") as file:
        file.write(
            json.dumps(costed_line(2.0, 2.0, basis="first", node="review", session_id="new")) + "\n"
        )

    roll_up_change(ledger, "add-marker")

    report = build_report(ledger, UNITS, group_by="unit")
    assert report.legacy.total_usd == pytest.approx(13.18)
    assert report.total.measured.cost_usd == pytest.approx(2.0)


def test_a_date_that_cuts_a_session_does_not_flag_it(worked: Path) -> None:
    cut = datetime(2026, 1, 1, 10, 3, tzinfo=UTC)

    report = build_report(worked, UNITS, group_by="unit", since=cut)

    (session,) = report.sessions
    assert report.total.measured.cost_usd == pytest.approx(TRUTH - 2.63 - 2.86)
    assert session.flagged is False
    assert session.incremental_usd == pytest.approx(TRUTH)


def test_a_legacy_call_folded_into_a_later_one_stays_in_the_legacy_count(tmp_path: Path) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        legacy_line(5.49, node="implement", session_id="s", at="2026-01-01T09:00:00+00:00"),
        costed_line(
            1.5,
            7.0,
            basis="derived",
            node="implement",
            session_id="s",
            resumed=True,
            at="2026-01-01T10:00:00+00:00",
        ),
    )

    report = build_report(ledger, UNITS, group_by="unit")

    assert report.legacy.count == 1
    assert report.legacy.total_usd == pytest.approx(5.49)
    assert report.total.measured.cost_usd == pytest.approx(1.5)


def test_a_zero_cumulative_figure_is_shown_as_zero(tmp_path: Path) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl", costed_line(0.0, 0.0, basis="first", session_id="free")
    )

    (session,) = build_report(ledger, UNITS, group_by="unit").sessions

    assert session.cumulative_usd == 0.0
    assert session.incremental_usd == 0.0


def test_the_reports_json_keeps_the_names_a_consumer_reads(worked: Path) -> None:
    body = json.loads(render_json(build_report(worked, UNITS, group_by="unit")))

    assert body["total"]["measured"]["cost_usd"] == pytest.approx(TRUTH)
    assert body["rows"][0]["measured"]["cost_usd"] == pytest.approx(TRUTH)
