"""Recorded wait data for the wait report's tests: a ledger, a decision log and a units
file, synthetic but pinned to the figures of the analysis that motivated them
(spec: unit-timeline-is-recorded).

`worked_example` is the analysis: 72 merged units with 1,343 h in `planned`, 172 h in
`in_review`, 93 h in `running` and 11.6 h of agent calls, and 88 hourly samples whose
first 87 hours had nothing running in 47 (17 with the queue full, 30 with room).
`all_causes` is one unit that spent time in every cause the report names.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.pipeline.spans import Sample
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME
from agent_build_kit.pipeline.wait_log import DECISIONS_NAME
from tests.factories import stored_unit
from tests.ledger_lines import agent_line, span_line, write_ledger

HOUR = 3_600_000
START = datetime(2026, 1, 1, tzinfo=UTC)

UNITS = 72
AGENT_MS = 580_000  # per unit: 72 of them are 11.6 h
CHECKS_MS = 600_000
SAMPLES = 88
IDLE_FULL = 17
IDLE_ROOM = 30
LIMIT = 3
REWORKED = 5  # units sent back for a round after their review began


class Recorded:
    """Where a fixture's files are, and the units its units file holds."""

    def __init__(self, state: Path, units: list[StoredUnit]) -> None:
        self.ledger = state / LEDGER_NAME
        self.decisions = state / DECISIONS_NAME
        self.units_file = state / "units.json"
        self.units = units


def at(hours: float, start: datetime = START) -> str:
    return (start + timedelta(hours=hours)).isoformat()


def write_units(path: Path, units: list[StoredUnit]) -> None:
    """The units file with the history the units carry, which `UnitStore.upsert` would restart."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"units": [u.model_dump(mode="json") for u in units]}))


def history(start: datetime, *stamps: tuple[str, float]) -> tuple[dict, ...]:
    return tuple({"state": state, "at": at(hours, start)} for state, hours in stamps)


def decision(unit: str, when: str, reason: str, waits_on: list[str]) -> dict:
    return {"at": when, "unit": unit, "reason": reason, "waits_on": waits_on, "tick": "t"}


def write_decisions(path: Path, decisions: list[dict]) -> None:
    path.write_text("".join(json.dumps(d) + "\n" for d in decisions))


def worked_example(state: Path) -> Recorded:
    units, ledger, decisions = [], [], []
    for i in range(UNITS):
        uid, change = f"change-{i}/1", f"change-{i}"
        ran = 19 if i < 47 else 18  # hours in planned
        in_review = ran + (2 if i < 21 else 1)  # hours in running
        merged = in_review + (3 if i < 28 else 2)  # hours in review
        ready = ran - 1
        t0 = START + timedelta(hours=i)
        # The first few units are sent back for rework an hour into their review: one hour
        # of the running time and two of the review time follow it, the totals unchanged.
        reworked = i < REWORKED
        stamps = (
            [("running", ran), ("in_review", ran + 1), ("running", ran + 2)]
            + [("in_review", ran + 3)]
            if reworked
            else [("running", ran), ("in_review", in_review)]
        )
        units.append(
            stored_unit(
                uid,
                change=change,
                state="merged",
                ready_at=t0 + timedelta(hours=ready),
                first_human_activity_at=t0 + timedelta(hours=merged - 1),
                history=history(t0, ("planned", 0), *stamps, ("merged", merged)),
            )
        )
        who = {"unit": uid, "change": change, "repo": "app"}
        ledger += [
            agent_line(**who, at=at(ran + 0.5, t0), duration_ms=AGENT_MS, session_id=f"s{i}"),
            span_line(
                **who, at=at(ran + 0.7, t0), command="uv run pytest", node="", duration_ms=CHECKS_MS
            ),
            span_line(
                **who,
                at=at(ran, t0),
                started=at(ready, t0),
                ended=at(ran, t0),
                node="",
                waited="slot",
                duration_ms=HOUR,
            ),
        ]
        if reworked:
            ledger.append(
                span_line(
                    **who,
                    at=at(ran + 3, t0),
                    started=at(ran + 2, t0),
                    ended=at(ran + 3, t0),
                    node="rework",
                    cause="review",
                    duration_ms=HOUR,
                )
            )
        decisions += [
            decision(uid, at(0, t0), "blocked", [f"change-{i - 1}/1"] if i else []),
            decision(uid, at(ready, t0), "slot", []),
            decision(uid, at(ran, t0), "none", []),
        ]
    for k in range(SAMPLES):
        idle_full, idle_room = k < IDLE_FULL, IDLE_FULL <= k < IDLE_FULL + IDLE_ROOM
        idle = idle_full or idle_room
        ledger.append(
            Sample(
                at=at(k),
                running=0 if idle else 2,
                in_review=LIMIT if idle_full else 1,
                blocked=4,
                queued=2,
                free_workers=LIMIT if idle else 1,
                limit=LIMIT,
                cap=LIMIT,
            ).model_dump()
        )
    write_ledger(state / LEDGER_NAME, *ledger)
    write_decisions(state / DECISIONS_NAME, decisions)
    write_units(state / "units.json", units)
    return Recorded(state, units)


ALL_CAUSES_START = datetime(2026, 1, 1, 20, tzinfo=UTC)
ALL_CAUSES_UNIT = "add-marker/1"
# What `all_causes` records for its unit, in hours.
ALL_CAUSES_HOURS = {
    "planned_blocked": 3,
    "planned_ready": 2,
    "running_agent": 1,
    "running_checks": 1.5,
    "paused": 1,
    "running_other": 1.5,
    "in_review_person": 3,
    "in_review_round": 1,
    "failed": 2,
    "wall": 16,
}


def all_causes(state: Path) -> Recorded:
    """A unit that waits 3 h for a prerequisite and 2 h for a slot, runs 4 h (1 h of agent,
    half an hour of checks, an hour paused, the rest other), is in review 4 h (a person
    answers after 3 h, and the other hour is checks'), fails for 2 h, runs 1 h more in a
    rework round after the review, and merges; and a unit with nothing
    recorded."""
    base = ALL_CAUSES_START
    who = {"unit": ALL_CAUSES_UNIT, "change": "add-marker", "repo": "app"}
    unit = stored_unit(
        ALL_CAUSES_UNIT,
        state="merged",
        ready_at=base + timedelta(hours=3),
        first_human_activity_at=base + timedelta(hours=12),
        history=history(
            base,
            ("planned", 0),
            ("running", 5),
            ("in_review", 9),
            ("failed", 13),
            ("running", 15),
            ("merged", 16),
        ),
    )
    silent = stored_unit("feature/1", change="feature")
    write_ledger(
        state / LEDGER_NAME,
        agent_line(**who, at=at(5.5, base), duration_ms=HOUR),
        span_line(**who, at=at(6, base), command="uv run pytest", node="", duration_ms=HOUR // 2),
        span_line(
            **who,
            at=at(5, base),
            started=at(3, base),
            ended=at(5, base),
            node="",
            waited="slot",
            duration_ms=2 * HOUR,
        ),
        span_line(
            **who,
            at=at(7, base),
            started=at(6, base),
            ended=at(7, base),
            node="",
            waited="usage_pause",
            duration_ms=HOUR,
        ),
        span_line(
            **who,
            at=at(16, base),
            started=at(15, base),
            ended=at(16, base),
            node="rework",
            cause="review",
            duration_ms=HOUR,
        ),
    )
    write_decisions(
        state / DECISIONS_NAME,
        [
            decision(ALL_CAUSES_UNIT, at(0, base), "blocked", ["add-marker/0"]),
            decision(ALL_CAUSES_UNIT, at(3, base), "slot", []),
            decision(ALL_CAUSES_UNIT, at(5, base), "none", []),
        ],
    )
    write_units(state / "units.json", [unit, silent])
    return Recorded(state, [unit, silent])
