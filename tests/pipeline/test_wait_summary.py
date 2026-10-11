"""A unit's summary holds all its wait figures (spec: unit-timeline-is-recorded).

The roll-up at archive turns a change's detail lines into one summary per unit. It reads
the slot and pause spans from the ledger, and the review stretch from the unit's history,
split into a person's time, the rounds' and the checks'.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.usage_report import build_report, roll_up_change
from tests.factories import stored_unit
from tests.ledger_lines import agent_line, span_line, write_ledger
from tests.wait_fixture import HOUR, START, at, history

CHANGE = "add-marker"
REVIEWED = "add-marker/1"
DIRECT = "add-marker/2"


def merged(uid: str, **overrides):
    return stored_unit(uid, state="merged", **overrides)


def units() -> list:
    """`REVIEWED` is 6 h in review, a person answering after 3 h; `DIRECT` is never reviewed."""
    return [
        merged(
            REVIEWED,
            first_human_activity_at=START.replace(hour=13),
            history=history(
                START, ("planned", 0), ("running", 4), ("in_review", 10), ("merged", 16)
            ),
        ),
        merged(DIRECT, history=history(START, ("planned", 0), ("running", 1), ("merged", 2))),
    ]


def ledger_of(tmp_path: Path) -> Path:
    return write_ledger(
        tmp_path / "state" / "usage-ledger.jsonl",
        agent_line(unit=REVIEWED),
        span_line(unit=REVIEWED, node="", waited="slot", duration_ms=2 * HOUR),
        span_line(unit=REVIEWED, node="", waited="usage_pause", duration_ms=HOUR),
        span_line(unit=REVIEWED, node="review", cause="review", duration_ms=HOUR),
        agent_line(unit=DIRECT, session_id="sess-2"),
        span_line(unit=DIRECT, node="", waited="slot", duration_ms=HOUR // 2),
    )


def summaries(ledger: Path) -> dict[str, dict]:
    lines = [json.loads(x) for x in ledger.read_text().splitlines() if x]
    return {x["unit"]: x for x in lines if x["kind"] == "summary"}


def test_a_summary_carries_the_slot_pause_and_review_waits(tmp_path: Path) -> None:
    ledger = ledger_of(tmp_path)

    roll_up_change(ledger, CHANGE, units())

    found = summaries(ledger)[REVIEWED]
    assert found["slot_wait_ms"] == 2 * HOUR
    assert found["pause_wait_ms"] == HOUR
    assert found["review_wait_ms"] == 6 * HOUR


def test_the_review_wait_is_split_into_person_round_and_checks(tmp_path: Path) -> None:
    ledger = ledger_of(tmp_path)

    roll_up_change(ledger, CHANGE, units())

    found = summaries(ledger)[REVIEWED]
    assert found["review_person_ms"] == 3 * HOUR
    assert found["review_round_ms"] == HOUR
    assert found["review_checks_ms"] == 2 * HOUR
    assert (
        found["review_person_ms"] + found["review_round_ms"] + found["review_checks_ms"]
        == found["review_wait_ms"]
    )


def test_a_review_nobody_answered_is_all_the_persons(tmp_path: Path) -> None:
    ledger = ledger_of(tmp_path)
    waiting = merged(
        REVIEWED,
        history=history(START, ("planned", 0), ("running", 4), ("in_review", 10), ("merged", 16)),
    )

    roll_up_change(ledger, CHANGE, [waiting, units()[1]])

    found = summaries(ledger)[REVIEWED]
    assert found["review_person_ms"] == 6 * HOUR
    assert found["review_checks_ms"] == 0


def test_every_unit_of_the_change_gets_the_three_figures(tmp_path: Path) -> None:
    ledger = ledger_of(tmp_path)

    roll_up_change(ledger, CHANGE, units())

    found = summaries(ledger)
    assert set(found) == {REVIEWED, DIRECT}
    for summary in found.values():
        assert {"slot_wait_ms", "pause_wait_ms", "review_wait_ms"} <= set(summary)
    assert found[DIRECT]["slot_wait_ms"] == HOUR // 2
    names = ("slot_wait_ms", "pause_wait_ms", "review_wait_ms")
    assert None not in [found[REVIEWED][n] for n in names], "a unit that had each wait has each"


def test_a_report_counts_a_rolled_up_review_wait_once(tmp_path: Path) -> None:
    ledger = ledger_of(tmp_path)
    stored = units()
    before = build_report(ledger, stored, group_by="change")

    roll_up_change(ledger, CHANGE, stored)

    after = build_report(ledger, stored, group_by="change")
    assert summaries(ledger)[REVIEWED]["review_wait_ms"] == 6 * HOUR, "it is in the summary now"
    assert before.total.review_wait_ms == 6 * HOUR
    assert after.total.review_wait_ms == 6 * HOUR
    assert after.total.slot_wait_ms == before.total.slot_wait_ms
    assert after.total.pause_wait_ms == before.total.pause_wait_ms


def test_an_older_summary_with_null_wait_figures_still_loads_and_reads_as_absent(
    tmp_path: Path,
) -> None:
    ledger = ledger_of(tmp_path)
    old = {
        "kind": "summary",
        "at": at(0),
        "unit": "feature/1",
        "change": "feature",
        "repo": "app",
        "slot_wait_ms": None,
        "pause_wait_ms": None,
        "review_wait_ms": None,
    }
    with ledger.open("a") as handle:
        handle.write(json.dumps(old) + "\n")

    roll_up_change(ledger, CHANGE, units())

    report = build_report(
        ledger, [*units(), stored_unit("feature/1", change="feature")], group_by="unit"
    )
    rows = {r.key: r for r in report.rows}
    assert rows["feature/1"].slot_wait_ms is None
    assert rows["feature/1"].pause_wait_ms is None
    assert rows["feature/1"].review_wait_ms is None
    assert rows[REVIEWED].slot_wait_ms == 2 * HOUR


def test_archiving_a_change_writes_the_figures_from_the_units_it_is_given(tmp_path: Path) -> None:
    ledger = ledger_of(tmp_path)
    (tmp_path / "openspec" / "changes" / CHANGE).mkdir(parents=True)

    def run(args: list[str], *, cwd: Path, **kwargs) -> subprocess.CompletedProcess:
        return subprocess.CompletedProcess(args, 0, "archived\n", "")

    archive_ready_changes(units(), planning_repo=tmp_path, run=run, usage_ledger=ledger)

    found = summaries(ledger)[REVIEWED]
    assert found["review_wait_ms"] == 6 * HOUR
    assert found["review_person_ms"] == 3 * HOUR
