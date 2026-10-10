"""`abk usage`: one-time repairs of the usage ledger.

`backfill-costs` is temporary: it turns the flat cost figures written before the `cost`
object into incremental ones, and is removed once every installation has run it.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

from agent_build_kit.installation import Installation
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_ledger import LEDGER_NAME, CostBasis, ledger_lock, read_lines
from agent_build_kit.pipeline.usage_report import roll_up_change

HELP = "temporary: removed once every installation has run it"


class _Plan(Frozen):
    """What the backfill would do to a ledger's lines."""

    lines: tuple[str, ...]
    before: dict[str, float]
    after: dict[str, float]
    changed: int
    unknown_sessions: tuple[str, ...]
    unknown_rows: int
    recompute: tuple[str, ...]  # changes whose summaries are rolled up again from their detail
    unrecoverable: tuple[str, ...]  # units whose summary has no detail left


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _is_legacy(raw: object) -> bool:
    return (
        isinstance(raw, dict)
        and raw.get("kind", "agent") == "agent"
        and not isinstance(raw.get("cost"), dict)
        and _number(raw.get("cost_usd")) is not None
    )


def _cost_of(
    raw: dict,
    cumulative: float | None,
    incremental: float | None,
    basis: CostBasis,
    reported: float | None,
):
    cost: dict[str, object] = {
        "incremental_usd": incremental,
        "cumulative_usd": cumulative,
        "basis": str(basis),
    }
    if reported is not None:
        cost["reported_usd"] = reported
    flat = {k: v for k, v in raw.items() if k not in ("cost_usd", "reported_cost_usd")}
    return flat | {"cost": cost}


def _when(value: object) -> datetime:
    """A ledger timestamp; one that does not read sorts first, so it never covers a later row."""
    try:
        at = datetime.fromisoformat(str(value))
    except ValueError:
        return datetime.min.replace(tzinfo=UTC)
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _reported(
    rows: list[dict], costed: list[tuple[str, float]], first: str
) -> dict[int, float | None]:
    """Each row's own reported figure, by position in `rows`.

    A Claude Code row stored the session's running reported total, so its figure is the
    difference from the row before (continuing from reported figures already costed); a
    figure that falls is left out. Other runtimes stored the call's own figure.
    """
    figures: dict[int, float | None] = {}
    previous = round(sum(v for at, v in costed if at <= first), 10)
    for n, raw in enumerate(rows):
        total = _number(raw.get("reported_cost_usd"))
        if total is None:
            figures[n] = None
        elif raw.get("runtime") != "claude_code":
            figures[n] = total
        else:
            figures[n] = round(total - previous, 10) if total >= previous else None
            previous = total
    return figures


def _plan(lines: list[str]) -> _Plan:
    parsed: list[dict | None] = []
    for line in lines:
        try:
            raw = json.loads(line)
        except ValueError:
            raw = None
        parsed.append(raw if isinstance(raw, dict) else None)

    sessions: dict[str, list[int]] = {}
    costed: dict[str, list[tuple[str, float]]] = {}
    costed_reported: dict[str, list[tuple[str, float]]] = {}
    for index, raw in enumerate(parsed):
        if raw is None:
            continue
        if _is_legacy(raw):
            sessions.setdefault(str(raw.get("session_id") or f"\0{index}"), []).append(index)
        elif isinstance(raw.get("cost"), dict) and raw.get("session_id"):
            figure = _number(raw["cost"].get("cumulative_usd"))
            if figure is not None:
                costed.setdefault(str(raw["session_id"]), []).append(
                    (str(raw.get("at", "")), figure)
                )
            own = _number(raw["cost"].get("reported_usd"))
            if own is not None:
                costed_reported.setdefault(str(raw["session_id"]), []).append(
                    (str(raw.get("at", "")), own)
                )

    rewritten: dict[int, dict] = {}
    unknown_sessions: list[str] = []
    for session, indexes in sessions.items():
        indexes.sort(key=lambda i: str((parsed[i] or {}).get("at", "")))
        rows = [parsed[i] or {} for i in indexes]
        running = [
            r.get("runtime") == "claude_code" and r.get("usage_source") == "reported" for r in rows
        ]
        totals = [_number(r["cost_usd"]) for r in rows]
        # A row already backfilled, or written by the new code, is the session's baseline.
        first = str(rows[0].get("at", ""))
        earlier = [c for c in sorted(costed.get(session, [])) if c[0] <= first]
        baseline = earlier[-1][1] if earlier else 0.0
        reported = _reported(rows, costed_reported.get(session, []), first)
        stored = [t for t, run in zip(totals, running, strict=True) if run and t is not None]
        if stored and earlier:
            stored = [baseline, *stored]
        if any(b < a for a, b in zip(stored, stored[1:], strict=False)):
            unknown_sessions.append(session)
            for n, (i, raw) in enumerate(zip(indexes, rows, strict=True)):
                rewritten[i] = _cost_of(raw, None, None, CostBasis.UNKNOWN, reported[n])
            continue
        previous, summed = baseline, baseline
        for n, (i, raw, total, is_total) in enumerate(
            zip(indexes, rows, totals, running, strict=True)
        ):
            assert total is not None
            if is_total:
                incremental, cumulative = round(total - previous, 10), total
                previous = total
            else:
                summed = round(summed + total, 10)
                incremental, cumulative = total, summed
            rewritten[i] = _cost_of(raw, cumulative, incremental, CostBasis.BACKFILLED, reported[n])

    before: dict[str, float] = {}
    after: dict[str, float] = {}
    for i, new in rewritten.items():
        unit = str(new.get("unit", ""))
        was = _number((parsed[i] or {}).get("cost_usd"))
        before[unit] = before.get(unit, 0.0) + (was or 0.0)
        after[unit] = after.get(unit, 0.0) + (new["cost"]["incremental_usd"] or 0.0)
    unknown_rows = sum(1 for new in rewritten.values() if new["cost"]["basis"] == "unknown")

    # The latest detail row of each unit: a summary built from its unit's detail is no later.
    detail: dict[str, datetime] = {}
    for r in parsed:
        if isinstance(r, dict) and r.get("kind", "agent") == "agent":
            at = _when(r.get("at"))
            unit = str(r.get("unit"))
            detail[unit] = max(at, detail.get(unit, at))
    out: list[str] = []
    recompute: list[str] = []
    unrecoverable: list[str] = []
    for i, line in enumerate(lines):
        raw = parsed[i]
        if i in rewritten:
            out.append(json.dumps(rewritten[i]))
        elif isinstance(raw, dict) and raw.get("kind") == "summary" and "cost_basis" not in raw:
            unit = str(raw.get("unit"))
            change = str(raw.get("change") or unit.split("/")[0])
            if unit in detail and detail[unit] <= _when(raw.get("at")):
                if change not in recompute:
                    recompute.append(change)
                continue
            unrecoverable.append(unit)
            out.append(json.dumps(raw | {"cost_basis": str(CostBasis.CUMULATIVE_SUMMED)}))
            if unit in detail and change not in recompute:
                recompute.append(change)  # rows after the summary are folded into it
        else:
            out.append(line)
    return _Plan(
        lines=tuple(out),
        before=before,
        after=after,
        changed=len(rewritten) - unknown_rows,
        unknown_sessions=tuple(unknown_sessions),
        unknown_rows=unknown_rows,
        recompute=tuple(recompute),
        unrecoverable=tuple(unrecoverable),
    )


def _report(plan: _Plan, *, applied: bool) -> None:
    verb = "applied" if applied else "dry run, nothing written; pass --apply to write"
    print(f"abk usage backfill-costs ({HELP}): {verb}")
    if not plan.before:
        print("no legacy rows")
    else:
        width = max(len(unit) for unit in (*plan.before, "overall")) + 2
        print(f"{'unit':<{width}}{'before':>12}{'after':>12}")
        for unit in sorted(plan.before):
            print(f"{unit:<{width}}{plan.before[unit]:>12.2f}{plan.after.get(unit, 0.0):>12.2f}")
        print(
            f"{'overall':<{width}}{sum(plan.before.values()):>12.2f}"
            f"{sum(plan.after.values()):>12.2f}"
        )
    print(f"rows changed: {plan.changed}")
    print(f"rows left unknown: {plan.unknown_rows}")
    for session in plan.unknown_sessions:
        print(f"unknown (a figure falls): session {session.lstrip(chr(0))}")
    for change in plan.recompute:
        print(f"summaries of {change} rolled up again with their detail rows")
    for unit in plan.unrecoverable:
        print(
            f"summary {unit}: its rolled-up detail is gone, marked "
            f"{CostBasis.CUMULATIVE_SUMMED} (not corrected)"
        )


def _write(ledger: Path, lines: list[str]) -> None:
    scratch = ledger.with_name(ledger.name + ".tmp")
    scratch.write_text("".join(f"{line}\n" for line in lines))
    os.replace(scratch, ledger)


def cmd_backfill_costs(args: argparse.Namespace, inst: Installation) -> int:
    ledger = inst.state_dir / LEDGER_NAME
    if not args.apply:
        _report(_plan(read_lines(ledger)), applied=False)
        return 0
    with ledger_lock(ledger):
        original = read_lines(ledger)
        plan = _plan(original)
        if list(plan.lines) != original:
            stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
            shutil.copyfile(ledger, ledger.with_name(f"usage-ledger-{stamp}.jsonl.bak"))
            _write(ledger, list(plan.lines))
    for change in plan.recompute:
        roll_up_change(ledger, change)
    _report(plan, applied=True)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser("usage", help="repairs of the usage ledger")
    commands = parser.add_subparsers(dest="usage_command", required=True)
    backfill = commands.add_parser("backfill-costs", help=HELP, description=HELP)
    backfill.add_argument(
        "--apply", action="store_true", help="write the ledger (default: dry run)"
    )
    backfill.set_defaults(func=cmd_backfill_costs)
