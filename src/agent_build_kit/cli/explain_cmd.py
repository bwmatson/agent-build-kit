"""`abk explain <unit> [--at TIME]`: why a unit was admitted, held or paused, from the records."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from agent_build_kit.cli.pipeline import store_for
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.admission_record import (
    ADMISSIONS_NAME,
    AdmissionRecord,
    config_fingerprint,
    read_admissions,
)
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import history_stamp


def _usage_line(record: AdmissionRecord) -> str:
    usage = record.usage
    facts = [
        f"source {usage.source}" if usage.source else "",
        f"age {usage.age_seconds:.0f}s" if usage.age_seconds is not None else "",
        f"threshold {usage.threshold}" if usage.threshold is not None else "",
        f"ramp {usage.ramp}" if usage.ramp is not None else "",
        f"on an estimate, {usage.estimate_starts} starts made on it" if usage.estimate else "",
    ]
    detail = "; ".join(fact for fact in facts if fact)
    if usage.may_start is None:
        return f"usage: {usage.reason}"
    verdict = "may start" if usage.may_start else "may not start"
    return f"usage: {verdict} — {usage.reason}" + (f" ({detail})" if detail else "")


_OUTCOMES = {
    "admitted": "admitted",
    "slot": "held, waiting for a slot",
    "usage": "refused by its account, so not started",
}


def _describe(record: AdmissionRecord, now_fingerprint: str) -> list[str]:
    outcome = _OUTCOMES[record.kind]
    lines = [
        f"{record.unit} was {outcome} at {record.at.isoformat()} (tick {record.tick})",
        f"slot {record.slot}: {len(record.counted)} counted, limit {record.limit}",
        *(f"  {each.id} ({each.state}): {each.why}" for each in record.counted),
        _usage_line(record),
        f"configuration {record.fingerprint}"
        + (
            " — made on stale configuration: the files have changed since"
            if record.fingerprint != now_fingerprint
            else ""
        ),
    ]
    return lines


def register(sub: argparse._SubParsersAction) -> None:
    explain = sub.add_parser(
        "explain", help="why a unit was admitted, held or paused, from the admission records"
    )
    explain.add_argument("unit", help="the unit id, e.g. add-marker/1")
    explain.add_argument(
        "--at", metavar="TIME", help="an ISO time; the latest record at or before it (default: now)"
    )
    explain.set_defaults(func=cmd_explain)


def cmd_explain(args: argparse.Namespace, inst: Installation) -> int:
    """Print why `args.unit` was admitted, held or paused at `args.at` (an ISO time, or None for
    the latest record)."""
    try:
        at = datetime.fromisoformat(args.at) if args.at else spans.clock.now()
    except ValueError:
        print("--at expects an ISO time", file=sys.stderr)
        return 2
    if at.tzinfo is None:
        at = at.replace(tzinfo=UTC)
    records = [
        each
        for each in read_admissions(inst.state_dir / ADMISSIONS_NAME)
        if each.unit == args.unit and each.at <= at
    ]
    record = records[-1] if records else None
    unit = next((each for each in store_for(inst).all() if each.id == args.unit), None)
    events = [
        (stamp, entry)
        for entry in (unit.history if unit else ())
        if str(entry.get("event", "")).startswith("usage_")
        and (stamp := history_stamp(entry)) is not None
        and stamp <= at
    ]
    paused = events[-1] if events and events[-1][1]["event"] == "usage_pause" else None
    if paused and (record is None or record.kind == "usage" or paused[0] >= record.at):
        stamp, entry = paused
        print(
            f"{args.unit} was paused since {stamp.isoformat()} by account {entry['account']}: "
            f"{entry['reason']}"
        )
        if record is not None and record.kind == "usage":
            print("\n".join(_describe(record, config_fingerprint(inst))))
        return 0
    if record is None and unit is not None and unit.cause is Cause.GATED and unit.note:
        print(f"{args.unit} is {unit.state.value}: {unit.note}")
        return 0
    if record is None:
        print(f"no record covers {args.unit} at {at.isoformat()}")
        return 0
    print("\n".join(_describe(record, config_fingerprint(inst))))
    return 0
