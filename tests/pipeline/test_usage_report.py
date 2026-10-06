"""The report over the usage ledger (spec: usage-reporting).

The ledger's lines are the report's input, so every test writes lines as the
capture and span code write them and reads the report's rows back: by any
grouping the sums equal the ledger's, estimates stand apart, an absent figure
reads as absent, and a damaged ledger still reads.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.usage_ledger import UsageRecord, append_record, ledger_lock
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
from tests.ledger_lines import agent_line, fixture_ledger, span_line, write_ledger

UNITS = [
    stored_unit("add-marker/1", repo="app"),
    stored_unit("add-marker/2", repo="platform"),
    stored_unit("feature/1", change="feature", repo="app"),
]

KEYS = {
    "unit": {"add-marker/1": 2, "add-marker/2": 1, "feature/1": 1},
    "change": {"add-marker": 3, "feature": 1},
    "node": {"implement": 3, "review": 1},
    "role": {"implement": 3, "review": 1},
    "model": {"model-a": 3, "model-b": 1},
    "repo": {"app": 3, "platform": 1},
    "day": {"2026-01-01": 1, "2026-01-02": 2, "2026-01-03": 1},
}


def row_of(report: Report, key: str) -> ReportRow:
    (row,) = [r for r in report.rows if r.key == key]
    return row


def summed(figures: Iterable[float | None]) -> float:
    """The sum of the figures a group recorded; a group with none is a test's failure."""
    present = [x for x in figures if x is not None]
    assert present, "no row recorded the figure"
    return sum(present)


@pytest.mark.parametrize("group_by", sorted(KEYS))
def test_rows_for_any_grouping_sum_to_the_ledgers_totals(tmp_path: Path, group_by: str) -> None:
    assert group_by in GROUPINGS
    report = build_report(fixture_ledger(tmp_path / "ledger.jsonl"), UNITS, group_by=group_by)

    assert {r.key: r.measured.calls for r in report.rows} == KEYS[group_by]
    rows = report.rows
    assert summed(r.measured.input_tokens for r in rows) == 147
    assert report.total.measured.input_tokens == 147
    assert summed(r.measured.output_tokens for r in rows) == 78
    assert summed(r.measured.cache_read_input_tokens for r in rows) == 1470
    assert summed(r.measured.cache_creation_input_tokens for r in rows) == 294
    assert summed(r.measured.cost_usd for r in rows) == pytest.approx(1.875)
    assert report.total.measured.cost_usd == pytest.approx(1.875)
    assert summed(r.agent_ms for r in rows) == 150000
    assert report.total.agent_ms == 150000


def test_a_row_carries_its_own_figures(tmp_path: Path) -> None:
    report = build_report(fixture_ledger(tmp_path / "ledger.jsonl"), UNITS, group_by="change")

    add_marker = row_of(report, "add-marker")
    assert add_marker.measured.input_tokens == 140
    assert add_marker.measured.cost_usd == pytest.approx(1.75)
    assert row_of(report, "feature").measured.output_tokens == 3


def test_the_repository_comes_from_the_unit_store(tmp_path: Path) -> None:
    """A call's own line may predate the field; the store knows where a unit lands."""
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        agent_line(repo=""),
        agent_line(unit="add-marker/2", repo="", session_id="sess-3"),
    )

    report = build_report(ledger, UNITS, group_by="repo")

    assert {r.key for r in report.rows} == {"app", "platform"}


def test_since_keeps_calls_on_or_after_the_date(tmp_path: Path) -> None:
    ledger = fixture_ledger(tmp_path / "ledger.jsonl")

    report = build_report(ledger, UNITS, group_by="unit", since=datetime(2026, 1, 2, tzinfo=UTC))

    assert {r.key for r in report.rows} == {"add-marker/1", "add-marker/2", "feature/1"}
    assert report.total.measured.calls == 3
    assert report.total.measured.input_tokens == 47


def test_change_and_unit_filters_narrow_the_rows(tmp_path: Path) -> None:
    ledger = fixture_ledger(tmp_path / "ledger.jsonl")

    by_change = build_report(ledger, UNITS, group_by="node", change="add-marker")
    by_unit = build_report(ledger, UNITS, group_by="node", unit="add-marker/1")

    assert by_change.total.measured.calls == 3
    assert {r.key: r.measured.calls for r in by_change.rows} == {"implement": 2, "review": 1}
    assert by_unit.total.measured.calls == 2
    assert by_unit.total.measured.input_tokens == 110


def test_a_changes_nodes_sum_to_the_changes_total(tmp_path: Path) -> None:
    """Spec scenario: a change's cost by node."""
    ledger = fixture_ledger(tmp_path / "ledger.jsonl")

    nodes = build_report(ledger, UNITS, group_by="node", change="add-marker")
    whole = build_report(ledger, UNITS, group_by="change", change="add-marker")

    assert summed(r.measured.cost_usd for r in nodes.rows) == pytest.approx(
        row_of(whole, "add-marker").measured.cost_usd
    )
    assert nodes.total.measured == whole.total.measured
    assert nodes.total.agent_ms == whole.total.agent_ms


def test_time_is_summed_by_bucket(tmp_path: Path) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        agent_line(duration_ms=60000),
        agent_line(node="review", round=1, session_id="sess-2", duration_ms=30000),
        # The node's own span duplicates the agent call and is no bucket of its own.
        span_line(duration_ms=99999),
        span_line(command="uv run pytest", duration_ms=3000),
        span_line(command="uv run ruff check", duration_ms=1500),
        span_line(waited="slot", duration_ms=5000),
        span_line(waited="usage_pause", duration_ms=7000),
    )
    units = [
        stored_unit(
            "add-marker/1",
            history=(
                {"state": "in_review", "at": "2026-01-01T12:00:00+00:00"},
                {"state": "merged", "at": "2026-01-01T14:00:00+00:00"},
            ),
        )
    ]

    row = row_of(build_report(ledger, units, group_by="unit"), "add-marker/1")

    assert row.agent_ms == 90000
    assert row.checks_ms == 4500
    assert row.slot_wait_ms == 5000
    assert row.pause_wait_ms == 7000
    assert row.review_wait_ms == 2 * 3600 * 1000


def test_a_bucket_never_recorded_is_absent_not_zero(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path / "ledger.jsonl", agent_line(duration_ms=None))

    row = row_of(build_report(ledger, UNITS, group_by="unit"), "add-marker/1")

    assert row.agent_ms is None
    assert row.checks_ms is None
    assert row.slot_wait_ms is None
    assert row.pause_wait_ms is None
    assert row.review_wait_ms is None


# --- estimates, absent figures, sources -----------------------------------------


def with_an_estimate(tmp_path: Path) -> Path:
    return write_ledger(
        tmp_path / "ledger.jsonl",
        agent_line(),
        agent_line(
            node="review",
            round=1,
            session_id="sess-2",
            input_tokens=1000,
            output_tokens=500,
            cache_read_input_tokens=None,
            cache_creation_input_tokens=None,
            cost_usd=0.3,
            usage_source="estimated",
        ),
    )


def test_estimates_have_their_own_column_and_stay_out_of_totals(tmp_path: Path) -> None:
    report = build_report(with_an_estimate(tmp_path), UNITS, group_by="unit")

    row = row_of(report, "add-marker/1")
    assert row.measured.calls == 1
    assert row.measured.input_tokens == 100
    assert row.measured.cost_usd == pytest.approx(1.0)
    assert row.estimated.calls == 1
    assert row.estimated.input_tokens == 1000
    assert row.estimated.cost_usd == pytest.approx(0.3)
    assert report.total.measured.input_tokens == 100
    assert report.total.estimated.input_tokens == 1000


def test_include_estimates_adds_them_to_the_totals(tmp_path: Path) -> None:
    report = build_report(
        with_an_estimate(tmp_path), UNITS, group_by="unit", include_estimates=True
    )

    row = row_of(report, "add-marker/1")
    assert row.measured.input_tokens == 1100
    assert row.measured.cost_usd == pytest.approx(1.3)
    assert row.estimated.input_tokens == 1000, "the estimated column still shows what was estimated"
    assert report.total.measured.input_tokens == 1100


def test_a_figure_never_recorded_is_absent_not_zero(tmp_path: Path) -> None:
    """A runtime that reported no cost has no cost: not a free call."""
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        agent_line(cost_usd=None, cache_read_input_tokens=None, cache_creation_input_tokens=None),
        agent_line(
            unit="feature/1",
            change="feature",
            session_id="sess-2",
            input_tokens=None,
            output_tokens=None,
            cost_usd=None,
            usage_source="none",
        ),
    )

    report = build_report(ledger, UNITS, group_by="unit")

    first = row_of(report, "add-marker/1")
    assert first.measured.cost_usd is None
    assert first.measured.cache_read_input_tokens is None
    assert first.measured.input_tokens == 100
    none = row_of(report, "feature/1")
    assert none.measured.calls == 1
    assert none.measured.input_tokens is None
    assert none.measured.output_tokens is None
    assert report.total.measured.cost_usd is None


def test_a_sum_over_calls_where_only_some_recorded_a_figure_counts_those_that_did(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        agent_line(cost_usd=None),
        agent_line(session_id="sess-2", cost_usd=0.5),
    )

    row = row_of(build_report(ledger, UNITS, group_by="unit"), "add-marker/1")

    assert row.measured.cost_usd == pytest.approx(0.5)


def test_each_rows_sources_are_shown(tmp_path: Path) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        agent_line(),
        agent_line(node="review", round=1, session_id="sess-2", usage_source="gateway"),
        agent_line(unit="add-marker/2", session_id="sess-3", usage_source="estimated"),
        agent_line(unit="feature/1", session_id="sess-4", usage_source="none"),
    )

    report = build_report(ledger, UNITS, group_by="unit")

    assert set(row_of(report, "add-marker/1").sources) == {"reported", "gateway"}
    assert set(row_of(report, "add-marker/2").sources) == {"estimated"}
    assert set(row_of(report, "feature/1").sources) == {"none"}
    assert set(report.total.sources) == {"reported", "gateway", "estimated", "none"}


# --- table and json -------------------------------------------------------------


def test_the_table_shows_a_row_per_group_its_columns_and_its_source(tmp_path: Path) -> None:
    report = build_report(fixture_ledger(tmp_path / "ledger.jsonl"), UNITS, group_by="unit")

    table = render_table(report)

    for key in KEYS["unit"]:
        assert key in table
    for heading in ("calls", "input", "output", "cache", "cost", "agent", "checks", "slot"):
        assert heading in table.lower()
    assert "reported" in table
    assert "gateway" in table


def test_the_table_shows_an_absent_figure_as_a_dash_never_a_zero(tmp_path: Path) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        agent_line(unit="feature/1", change="feature", cost_usd=None, usage_source="none"),
    )

    table = render_table(build_report(ledger, UNITS, group_by="unit"))

    (line,) = [x for x in table.splitlines() if x.startswith("feature/1")]
    assert "-" in line.split()
    assert "0.00" not in line


def test_the_table_has_estimates_in_a_column_of_their_own(tmp_path: Path) -> None:
    table = render_table(build_report(with_an_estimate(tmp_path), UNITS, group_by="unit"))

    assert "estimated" in table.lower()
    assert "1000" in table.replace(",", "")


def test_json_carries_the_same_rows(tmp_path: Path) -> None:
    report = build_report(fixture_ledger(tmp_path / "ledger.jsonl"), UNITS, group_by="model")

    document = json.loads(render_json(report))

    assert document["group_by"] == "model"
    assert {r["key"]: r["measured"]["calls"] for r in document["rows"]} == KEYS["model"]
    assert document["rows"] == [r.model_dump(mode="json") for r in report.rows]
    assert document["total"]["measured"]["input_tokens"] == 147
    assert document["total"]["measured"]["cost_usd"] == pytest.approx(1.875)
    assert document["rows"][0]["estimated"]["calls"] == 0


def test_json_keeps_an_absent_figure_null(tmp_path: Path) -> None:
    ledger = write_ledger(tmp_path / "ledger.jsonl", agent_line(cost_usd=None))

    document = json.loads(render_json(build_report(ledger, UNITS, group_by="unit")))

    assert document["rows"][0]["measured"]["cost_usd"] is None
    assert document["rows"][0]["checks_ms"] is None


def gateway_call_with_a_reported_figure() -> dict:
    return agent_line(
        usage_source="gateway",
        input_tokens=120,
        output_tokens=60,
        cost_usd=1.2,
        reported={
            "input_tokens": 100,
            "output_tokens": 55,
            "cache_read_input_tokens": None,
            "cache_creation_input_tokens": None,
        },
        reported_cost_usd=1.0,
    )


def test_a_call_with_a_reported_and_a_gateway_figure_shows_both_and_the_difference(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(tmp_path / "ledger.jsonl", gateway_call_with_a_reported_figure())

    row = row_of(build_report(ledger, UNITS, group_by="unit"), "add-marker/1")

    assert row.measured.input_tokens == 120
    assert row.measured.cost_usd == pytest.approx(1.2)
    assert row.difference is not None
    assert row.difference.reported_input_tokens == 100
    assert row.difference.reported_output_tokens == 55
    assert row.difference.reported_cost_usd == pytest.approx(1.0)
    assert row.difference.input_tokens == 20
    assert row.difference.output_tokens == 5
    assert row.difference.cost_usd == pytest.approx(0.2)


def test_the_difference_is_in_the_json_and_absent_where_there_is_nothing_to_compare(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        gateway_call_with_a_reported_figure(),
        agent_line(unit="feature/1", change="feature", session_id="sess-2"),
    )

    document = json.loads(render_json(build_report(ledger, UNITS, group_by="unit")))

    rows = {r["key"]: r for r in document["rows"]}
    assert rows["add-marker/1"]["difference"]["input_tokens"] == 20
    assert rows["feature/1"]["difference"] is None


# --- a damaged ledger -----------------------------------------------------------


def test_a_half_written_line_is_skipped_and_the_rest_read(tmp_path: Path) -> None:
    whole = json.dumps(agent_line(unit="feature/1", change="feature", session_id="sess-2"))
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        agent_line(),
        json.dumps(agent_line(session_id="sess-9"))[:60],
        json.dumps(span_line(waited="slot"))[:30],
        "",
        whole,
    )

    report = build_report(ledger, UNITS, group_by="unit")

    assert {r.key: r.measured.calls for r in report.rows} == {"add-marker/1": 1, "feature/1": 1}


def test_a_line_from_a_later_version_with_fields_this_one_lacks_still_counts(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        agent_line(thinking_tokens=9, region="eu", extra={"nested": [1, 2]}),
        span_line(waited="slot", duration_ms=2000, queue="q1"),
        {"kind": "something-new", "at": "2026-01-01T10:00:00+00:00", "unit": "add-marker/1"},
    )

    row = row_of(build_report(ledger, UNITS, group_by="unit"), "add-marker/1")

    assert row.measured.calls == 1
    assert row.measured.input_tokens == 100
    assert row.slot_wait_ms == 2000


def test_a_call_written_twice_is_counted_once(tmp_path: Path) -> None:
    """A re-run of a node writes the same unit, node, round and session again."""
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        agent_line(cost_usd=0.5, at="2026-01-01T10:00:00+00:00"),
        agent_line(cost_usd=0.9, at="2026-01-01T10:30:00+00:00"),
    )

    report = build_report(ledger, UNITS, group_by="unit")

    assert report.total.measured.calls == 1
    assert report.total.measured.cost_usd == pytest.approx(0.9)


def test_a_missing_ledger_reports_nothing(tmp_path: Path) -> None:
    report = build_report(tmp_path / "absent.jsonl", UNITS, group_by="unit")

    assert report.rows == ()
    assert report.total.measured.calls == 0


# --- archive ---------------------------------------------------------------------


class FakeRunner:
    def __call__(self, args: list[str], *, cwd: Path, **kwargs):
        import subprocess

        return subprocess.CompletedProcess(args, 0, "archived\n", "")


def merged(uid: str, **overrides):
    return stored_unit(uid, **{"state": "merged", **overrides})


def archive_ledger(tmp_path: Path) -> Path:
    return write_ledger(
        tmp_path / "state" / "usage-ledger.jsonl",
        agent_line(),
        agent_line(node="review", round=1, role="review", session_id="sess-2", cost_usd=0.25),
        agent_line(unit="add-marker/2", repo="platform", session_id="sess-3", cost_usd=None),
        agent_line(
            unit="add-marker/2",
            repo="platform",
            node="review",
            round=1,
            session_id="sess-5",
            usage_source="estimated",
            cost_usd=0.3,
        ),
        agent_line(unit="feature/1", change="feature", session_id="sess-4", cost_usd=0.125),
        span_line(command="uv run pytest", duration_ms=3000),
        span_line(unit="add-marker/2", waited="slot", duration_ms=5000),
        span_line(unit="feature/1", change="feature", waited="usage_pause", duration_ms=7000),
    )


def ledger_lines(path: Path) -> list[dict]:
    return [json.loads(x) for x in path.read_text().splitlines() if x]


def test_archiving_a_change_replaces_its_detail_with_one_summary_per_unit(
    tmp_path: Path,
) -> None:
    ledger = archive_ledger(tmp_path)
    units = [merged("add-marker/1"), merged("add-marker/2", repo="platform")]

    archived = archive_ready_changes(
        units, planning_repo=tmp_path, run=FakeRunner(), usage_ledger=ledger
    )

    assert archived == ["add-marker"]
    lines = ledger_lines(ledger)
    mine = [x for x in lines if x["unit"].startswith("add-marker")]
    assert sorted((x["kind"], x["unit"]) for x in mine) == [
        ("summary", "add-marker/1"),
        ("summary", "add-marker/2"),
    ]
    untouched = [x for x in lines if x["unit"] == "feature/1"]
    assert sorted(x["kind"] for x in untouched) == ["agent", "span"]


def test_the_reports_totals_for_an_archived_change_are_unchanged(tmp_path: Path) -> None:
    ledger = archive_ledger(tmp_path)
    units = [merged("add-marker/1"), merged("add-marker/2", repo="platform")]
    reporting = [*units, stored_unit("feature/1", change="feature")]
    before = {
        by: build_report(ledger, reporting, group_by=by, include_estimates=True)
        for by in ("unit", "change", "repo")
    }

    archive_ready_changes(units, planning_repo=tmp_path, run=FakeRunner(), usage_ledger=ledger)

    for by, report in before.items():
        after = build_report(ledger, reporting, group_by=by, include_estimates=True)
        assert after.model_dump() == report.model_dump(), by
    assert before["change"].total.measured.calls == 5


def test_a_summary_keeps_the_estimated_figures_apart_and_the_source_mix(tmp_path: Path) -> None:
    ledger = archive_ledger(tmp_path)
    units = [merged("add-marker/1"), merged("add-marker/2", repo="platform")]

    archive_ready_changes(units, planning_repo=tmp_path, run=FakeRunner(), usage_ledger=ledger)

    row = row_of(build_report(ledger, units, group_by="unit"), "add-marker/2")
    assert row.estimated.cost_usd == pytest.approx(0.3)
    assert row.measured.cost_usd is None, "a figure never recorded is still absent"
    assert set(row.sources) == {"reported", "estimated"}
    assert row.slot_wait_ms == 5000


def test_archiving_with_no_ledger_still_archives_and_keeps_the_detail_of_a_change_not_archived(
    tmp_path: Path,
) -> None:
    ledger = archive_ledger(tmp_path)
    before = ledger.read_text()
    waiting = [merged("add-marker/1"), merged("add-marker/2", state="in_review")]

    assert (
        archive_ready_changes(
            waiting, planning_repo=tmp_path, run=FakeRunner(), usage_ledger=ledger
        )
        == []
    )
    assert ledger.read_text() == before

    archived = archive_ready_changes(
        [merged("add-marker/1")],
        planning_repo=tmp_path,
        run=FakeRunner(),
        usage_ledger=tmp_path / "state" / "none.jsonl",
    )

    assert archived == ["add-marker"]
    assert not (tmp_path / "state" / "none.jsonl").exists()
    # And the change that did archive left its summary behind in the real ledger.
    archive_ready_changes(
        [merged("add-marker/1"), merged("add-marker/2")],
        planning_repo=tmp_path,
        run=FakeRunner(),
        usage_ledger=ledger,
    )
    assert {x["kind"] for x in ledger_lines(ledger) if x["unit"].startswith("add-marker")} == {
        "summary"
    }


# --- a damaged or contended ledger -------------------------------------------------


def test_a_line_cut_off_inside_a_multibyte_character_is_skipped_and_the_rest_read(
    tmp_path: Path,
) -> None:
    ledger = write_ledger(tmp_path / "ledger.jsonl", agent_line(cost_usd=2.5))
    with ledger.open("ab") as handle:
        handle.write(b'{"kind":"agent","outcome":"\xe2\x80')

    report = build_report(ledger, UNITS, group_by="unit")

    assert row_of(report, "add-marker/1").measured.cost_usd == pytest.approx(2.5)


def test_a_line_appended_while_a_change_archives_is_not_lost(tmp_path: Path) -> None:
    ledger = archive_ledger(tmp_path)
    late = UsageRecord.model_validate(
        agent_line(unit="feature/1", change="feature", session_id="sess-late", cost_usd=8.0)
    )
    appended = threading.Event()

    def append_late() -> None:
        append_record(ledger, late)
        appended.set()

    with ledger_lock(ledger):
        rolling = threading.Thread(target=roll_up_change, args=(ledger, "add-marker"))
        rolling.start()
        writer = threading.Thread(target=append_late)
        writer.start()
        assert not appended.wait(0.3), "an append waits for the roll-up's lock"
        assert rolling.is_alive(), "the roll-up waits for the ledger lock"
        held = {x["kind"] for x in ledger_lines(ledger) if x["unit"].startswith("add-marker")}
        assert held != {"summary"}, "the ledger is untouched while the lock is held"
    rolling.join(10)
    writer.join(10)

    lines = ledger_lines(ledger)
    assert "sess-late" in [x.get("session_id") for x in lines]
    assert {x["kind"] for x in lines if x["unit"].startswith("add-marker")} == {"summary"}
