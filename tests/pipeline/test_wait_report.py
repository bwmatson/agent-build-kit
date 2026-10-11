"""The waits report: wall time by cause, the hours nothing ran, and the estimate ratio
(spec: usage-reporting, unit-timeline-is-recorded).

The input is recorded data: a ledger with spans and samples, the decision log and the
units' histories. The worked example is the analysis the change grew from.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.usage_report import (
    WAIT_GROUPINGS,
    WaitReport,
    WaitRow,
    build_wait_report,
    render_json,
    render_waits,
)
from tests.factories import stored_unit
from tests.ledger_lines import span_line, write_ledger
from tests.wait_fixture import (
    ALL_CAUSES_HOURS,
    ALL_CAUSES_UNIT,
    HOUR,
    START,
    Recorded,
    all_causes,
    at,
    decision,
    history,
    worked_example,
    write_decisions,
)

CAUSES = (
    "planned_blocked_ms",
    "planned_ready_ms",
    "running_agent_ms",
    "running_checks_ms",
    "running_other_ms",
    "in_review_person_ms",
    "in_review_round_ms",
    "paused_ms",
    "failed_ms",
)


def waits(recorded: Recorded, group_by: str = "unit") -> WaitReport:
    return build_wait_report(recorded.ledger, recorded.decisions, recorded.units, group_by=group_by)


def caused(row: WaitRow) -> int:
    return sum(getattr(row, name) or 0 for name in CAUSES)


# --- the recorded analysis ----------------------------------------------------------------


def test_the_worked_example_reproduces_the_analysis(tmp_path: Path) -> None:
    total = waits(worked_example(tmp_path)).total

    assert total.planned_ms == 1343 * HOUR
    assert total.in_review_ms == 172 * HOUR
    assert total.running_ms == 93 * HOUR
    assert total.running_agent_ms == 41_760_000, "11.6 h of agent calls"
    assert total.wall_ms == (1343 + 172 + 93) * HOUR


def test_the_worked_example_has_a_row_for_each_merged_unit(tmp_path: Path) -> None:
    report = waits(worked_example(tmp_path))

    assert len(report.rows) == 72
    assert caused(report.total) == report.total.wall_ms


def test_hours_with_nothing_running_split_into_a_full_queue_and_room(tmp_path: Path) -> None:
    """Each sample stands for the time to the next, so 88 hourly samples observe 87 hours."""
    idle = waits(worked_example(tmp_path)).idle

    assert idle.observed_h == pytest.approx(87)
    assert idle.idle_h == pytest.approx(47)
    assert idle.queue_full_h == pytest.approx(17)
    assert idle.room_h == pytest.approx(30)


def test_a_ledger_without_samples_observes_no_hours(tmp_path: Path) -> None:
    recorded = all_causes(tmp_path)

    assert waits(recorded).idle.observed_h == 0


# --- the causes -----------------------------------------------------------------------


def test_each_cause_of_a_unit_is_the_time_the_records_give_it(tmp_path: Path) -> None:
    (row,) = [r for r in waits(all_causes(tmp_path)).rows if r.key == ALL_CAUSES_UNIT]

    for cause, hours in ALL_CAUSES_HOURS.items():
        name = "wall_ms" if cause == "wall" else f"{cause}_ms"
        assert getattr(row, name) == hours * HOUR, cause


def test_the_causes_sum_to_each_units_wall_time(tmp_path: Path) -> None:
    report = waits(all_causes(tmp_path))
    (row,) = [r for r in report.rows if r.key == ALL_CAUSES_UNIT]

    assert caused(row) == row.wall_ms
    assert caused(report.total) == report.total.wall_ms


def test_a_unit_with_no_records_has_every_figure_absent_not_zero(tmp_path: Path) -> None:
    (row,) = [r for r in waits(all_causes(tmp_path)).rows if r.key == "feature/1"]

    assert row.wall_ms is None
    assert [getattr(row, name) for name in CAUSES] == [None] * len(CAUSES)
    assert row.planned_ms is None
    assert row.running_ms is None
    assert row.in_review_ms is None


def test_a_unit_with_no_review_has_the_review_causes_absent(tmp_path: Path) -> None:
    recorded = all_causes(tmp_path)
    direct = stored_unit(
        "add-marker/2",
        state="merged",
        history=history(START, ("planned", 0), ("running", 1), ("merged", 2)),
    )

    report = build_wait_report(
        recorded.ledger, recorded.decisions, [*recorded.units, direct], group_by="unit"
    )

    (row,) = [r for r in report.rows if r.key == "add-marker/2"]
    assert row.in_review_person_ms is None
    assert row.in_review_round_ms is None
    assert row.wall_ms == HOUR, "its planned stretch has no ready stamp, so it is left out"


# --- regrouping -----------------------------------------------------------------------


@pytest.mark.parametrize("group_by", WAIT_GROUPINGS)
def test_any_grouping_gives_the_same_total(tmp_path: Path, group_by: str) -> None:
    recorded = all_causes(tmp_path)
    by_unit = waits(recorded, "unit")

    report = waits(recorded, group_by)

    assert report.group_by == group_by
    assert report.total == by_unit.total.model_copy(update={"key": report.total.key})
    for name in ("wall_ms", *CAUSES):
        parts = [getattr(r, name) for r in report.rows if getattr(r, name) is not None]
        assert sum(parts) == getattr(by_unit.total, name), name


def test_grouped_by_day_a_unit_over_midnight_is_in_more_than_one_row(tmp_path: Path) -> None:
    report = waits(all_causes(tmp_path), "day")

    assert len(report.rows) > 1
    assert [r.key for r in report.rows] == sorted(r.key for r in report.rows)


def test_a_grouping_that_is_not_offered_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="node"):
        waits(all_causes(tmp_path), "node")


# --- as JSON and as a table -----------------------------------------------------------------


def test_the_json_carries_the_reports_rows(tmp_path: Path) -> None:
    report = waits(all_causes(tmp_path))

    document = json.loads(render_json(report))

    assert [r["key"] for r in document["rows"]] == [r.key for r in report.rows]
    for row, raw in zip(report.rows, document["rows"], strict=True):
        for name in ("wall_ms", *CAUSES):
            assert raw[name] == getattr(row, name), name
    assert document["total"]["wall_ms"] == report.total.wall_ms
    assert document["idle"]["observed_h"] == report.idle.observed_h


def test_the_table_shows_the_analysis_figures(tmp_path: Path) -> None:
    lines = render_waits(waits(worked_example(tmp_path))).splitlines()

    assert "hours: planned 1343.0, in review 172.0, running 93.0 (agent 11.6)" in lines
    assert "nothing ran for 47 of 87 hours: 17 with a full queue, 30 with room" in lines


# --- the estimate ratio ---------------------------------------------------------------------


def sized(uid: str, estimated: int, actual: int | None, **overrides):
    return stored_unit(
        uid,
        change=uid.split("/")[0],
        state="merged",
        estimated_lines=estimated,
        actual_lines=actual,
        **overrides,
    )


def test_the_estimate_ratio_is_actual_over_estimated_lines_per_kind(tmp_path: Path) -> None:
    units = [
        sized("a/1", 100, 150),
        sized("b/1", 200, 450),
        sized("c/1", 100, 80, repo="platform", tier="tier2"),
        sized("d/1", 100, None),
    ]

    report = build_wait_report(
        tmp_path / "ledger.jsonl", tmp_path / "decisions.jsonl", units, group_by="unit"
    )

    found = {e.kind: (e.ratio, e.units) for e in report.estimates}
    assert found == {
        "app tier1": (pytest.approx(2.0), 2),
        "platform tier2": (pytest.approx(0.8), 1),
    }


def test_the_table_prints_the_estimate_ratio_per_kind(tmp_path: Path) -> None:
    report = build_wait_report(
        tmp_path / "ledger.jsonl",
        tmp_path / "decisions.jsonl",
        [sized("a/1", 100, 150), sized("b/1", 200, 450)],
        group_by="unit",
    )

    table = render_waits(report)

    assert "app tier1" in table
    assert "2.0" in table


def test_no_estimate_to_compare_leaves_the_ratios_empty(tmp_path: Path) -> None:
    report = build_wait_report(
        tmp_path / "ledger.jsonl",
        tmp_path / "decisions.jsonl",
        [sized("a/1", 100, None)],
        group_by="unit",
    )

    assert report.estimates == ()


def test_a_missing_ledger_and_decision_log_report_the_stores_units(tmp_path: Path) -> None:
    report = build_wait_report(
        tmp_path / "ledger.jsonl",
        tmp_path / "decisions.jsonl",
        [stored_unit("add-marker/1")],
        group_by="unit",
    )

    assert [r.key for r in report.rows] == ["add-marker/1"]
    assert report.total.wall_ms is None


# --- review rounds and ready stamps --------------------------------------------------------


def test_a_round_before_the_first_review_is_running_time_and_one_after_is_a_rounds(
    tmp_path: Path,
) -> None:
    """running -> in_review -> running (rework) -> in_review -> merged, with an internal round."""
    unit = stored_unit(
        "add-marker/1",
        state="merged",
        ready_at=START,
        first_human_activity_at=at(8),
        history=history(
            START,
            ("planned", 0),
            ("running", 1),
            ("in_review", 5),
            ("running", 8),
            ("in_review", 10),
            ("merged", 12),
        ),
    )
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        span_line(
            unit=unit.id,
            node="rework",
            cause="review",
            started=at(2),
            ended=at(3),
            duration_ms=HOUR,
        ),
        span_line(
            unit=unit.id,
            node="fix_checks",
            cause="check",
            started=at(8),
            ended=at(9),
            duration_ms=HOUR,
        ),
    )

    report = build_wait_report(ledger, tmp_path / "decisions.jsonl", [unit])

    (row,) = report.rows
    assert row.in_review_round_ms == HOUR, "only the round after the review began"
    assert row.in_review_person_ms == 3 * HOUR, "answered 3 h in: the review is not shortened"
    assert row.running_checks_ms == 2 * HOUR, "the 5 h in review less the person's 3 h"
    assert row.running_other_ms == 5 * HOUR, "both running stretches less the round"
    assert caused(row) == row.wall_ms == 12 * HOUR


def test_a_unit_ready_at_its_first_slot_decision_starts_waiting_there(tmp_path: Path) -> None:
    """A full queue is a reason too, but `mark_ready` stamps only a unit that could start."""
    unit = stored_unit(
        "add-marker/1",
        state="merged",
        history=history(START, ("planned", 0), ("running", 6), ("merged", 7)),
    )
    write_decisions(
        tmp_path / "decisions.jsonl",
        [
            decision(unit.id, at(0), "blocked", ["add-marker/0"]),
            decision(unit.id, at(2), "queue_full", []),
            decision(unit.id, at(4), "slot", []),
            decision(unit.id, at(6), "none", []),
        ],
    )

    report = build_wait_report(tmp_path / "ledger.jsonl", tmp_path / "decisions.jsonl", [unit])

    (row,) = report.rows
    assert row.planned_blocked_ms == 4 * HOUR
    assert row.planned_ready_ms == 2 * HOUR


def test_a_round_in_a_planned_stretch_without_a_ready_stamp_is_still_a_rounds(
    tmp_path: Path,
) -> None:
    unit = stored_unit(
        "add-marker/1",
        state="merged",
        history=history(
            START,
            ("planned", 0),
            ("running", 1),
            ("in_review", 2),
            ("planned", 3),
            ("running", 5),
            ("merged", 6),
        ),
    )
    ledger = write_ledger(
        tmp_path / "ledger.jsonl",
        span_line(
            unit=unit.id,
            node="adapt",
            cause="conflict",
            started=at(3),
            ended=at(4),
            duration_ms=HOUR,
        ),
    )

    (row,) = build_wait_report(ledger, tmp_path / "decisions.jsonl", [unit]).rows

    assert row.in_review_round_ms == HOUR
    assert row.planned_blocked_ms is None
    assert row.planned_ms == 3 * HOUR, "the time in the state is told whole"
