"""Reads the usage ledger back as rows, for `abk report`, the summary page and
the archive roll-up.

The reader keeps one record per unit, node, round and session, tolerates
half-written lines and fields it does not know, joins unit metadata from the
store, and groups by unit, change, node, role, model, repository or day.
Estimated figures sit in their own column and are left out of totals unless
asked for; a figure never recorded is `None`, not zero.

A change's detail lines are rolled up into one `summary` line per unit when it
is archived. The line keeps the unit's totals and a `breakdown`: one item per
node, role, model and usage source, ordered by that key, whose items sum to the
totals, so a report splits archived work as it splits live work. A waiting node
that made no call has an item whose role and model are `(none)`. A summary
written before breakdowns existed has none; it still totals, and reads as one
row labelled `(archived, no breakdown)` in the node, role and model views.
"""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.file_lock import atomic_write_text
from agent_build_kit.pipeline.unit_size import Kind, kind_of, measured
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, PLANNED, RUNNING
from agent_build_kit.pipeline.usage_ledger import (
    CostBasis,
    UsageRecord,
    combine_records,
    grouped_records,
    ledger_lock,
    read_lines,
)
from agent_build_kit.pipeline.vocabulary import WaitReason

GROUPINGS = ("unit", "change", "node", "role", "model", "repo", "day")

# A session's increments this far from its final cumulative figure still add up.
SESSION_TOLERANCE = 1e-6
NONE = "(none)"
NO_BREAKDOWN = "(archived, no breakdown)"
TOP_UNITS = 10
# A gateway figure this far from what the agent reported is flagged in the table.
LARGE_DIFFERENCE = 0.10

_COUNTS = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
)
_TIMES = (
    "agent_ms",
    "checks_ms",
    "slot_wait_ms",
    "pause_wait_ms",
    "review_wait_ms",
    "review_person_ms",
    "review_round_ms",
    "review_checks_ms",
)


class Figures(Frozen):
    """Counts summed over some calls; a figure no call recorded is None."""

    calls: int = 0
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cost_usd: float | None = None


class Difference(Frozen):
    """For calls with both a gateway and an agent-reported figure: the reported
    sums and gateway minus reported, for each figure both have."""

    reported_input_tokens: int | None = None
    reported_output_tokens: int | None = None
    reported_cost_usd: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    cost_usd: float | None = None


class ReportRow(Frozen):
    """One group: measured figures, estimated ones apart, time by bucket in
    milliseconds, the sources the figures came from, and any difference."""

    key: str
    measured: Figures
    estimated: Figures
    agent_ms: int | None = None
    checks_ms: int | None = None
    slot_wait_ms: int | None = None
    pause_wait_ms: int | None = None
    review_wait_ms: int | None = None
    # `review_wait_ms` split by who or what the unit waited on in review.
    review_person_ms: int | None = None
    review_round_ms: int | None = None
    review_checks_ms: int | None = None
    sources: tuple[str, ...] = ()
    difference: Difference | None = None


class SessionRow(Frozen):
    """One session: the sum of its calls' increments beside its final cumulative cost."""

    session_id: str
    incremental_usd: float | None = None
    cumulative_usd: float | None = None
    flagged: bool = False


class LegacyRow(Frozen):
    unit: str
    node: str
    legacy_usd: float


class Legacy(Frozen):
    """The rows written before costs were incremental, kept apart from every sum."""

    count: int = 0
    total_usd: float | None = None
    rows: tuple[LegacyRow, ...] = ()


class Report(Frozen):
    group_by: str
    rows: tuple[ReportRow, ...]
    total: ReportRow
    # The calls with no unit, one row per node, which the by-unit view keeps out of `rows`.
    overhead: tuple[ReportRow, ...] = ()
    sessions: tuple[SessionRow, ...] = ()
    legacy: Legacy = Legacy()
    unknown_calls: int = 0  # calls whose incremental cost could not be known


WAIT_GROUPINGS = ("unit", "day")


class WaitRow(Frozen):
    """One group's wall time by cause, and its time in each state, in milliseconds; one
    never recorded is None."""

    key: str
    wall_ms: int | None = None
    planned_blocked_ms: int | None = None
    planned_ready_ms: int | None = None
    running_agent_ms: int | None = None
    running_checks_ms: int | None = None
    running_other_ms: int | None = None
    in_review_person_ms: int | None = None
    in_review_round_ms: int | None = None
    paused_ms: int | None = None
    failed_ms: int | None = None

    # The time in each state, whatever the causes divide it into.
    planned_ms: int | None = None
    running_ms: int | None = None
    in_review_ms: int | None = None


class IdleHours(Frozen):
    """The hours the samples observed, and those in which nothing ran, split by
    whether the queue was full."""

    observed_h: float = 0.0
    idle_h: float = 0.0
    queue_full_h: float = 0.0
    room_h: float = 0.0


class EstimateRatio(Frozen):
    """Actual over estimated lines, summed over a kind's merged units that have both."""

    kind: str
    ratio: float
    units: int


class WaitReport(Frozen):
    group_by: str
    rows: tuple[WaitRow, ...]
    total: WaitRow
    idle: IdleHours = IdleHours()
    estimates: tuple[EstimateRatio, ...] = ()


# How many of the steps that added the most the context report lists.
BIGGEST = 10


class StepContext(Frozen):
    """One step kind's context use over the calls that report it: the mean and 90th
    percentile of what a call added, the compactions, and the end fill as tokens used
    over the window; `peak` only where it differs from the end fill."""

    node: str
    calls: int
    mean_added: float
    p90_added: float
    compactions: int
    used_end: int
    max: int | None = None
    peak: int | None = None


class SessionContext(Frozen):
    """One session's fill after each of its steps, in order."""

    session_id: str
    fills: tuple[int, ...]


class Adder(Frozen):
    """A step and what it added to the context."""

    unit: str
    node: str
    round: int
    added: int


class ContextReport(Frozen):
    steps: tuple[StepContext, ...] = ()
    sessions: tuple[SessionContext, ...] = ()
    biggest: tuple[Adder, ...] = ()  # largest first
    unknown_calls: int = 0  # calls with no context figures, left out of the means


class _Entry(Frozen):
    """One contribution to the report — a call, a span, a summary or a review
    wait — with what it can be grouped by."""

    unit: str
    change: str
    repo: str
    node: str = NONE
    role: str = NONE
    model: str = NONE
    runtime: str = ""
    usage_source: str = ""
    at: datetime | None = None
    row: ReportRow
    call: UsageRecord | None = None  # the ledger record, for what is read off the call itself
    parts: tuple[UsageRecord, ...] = ()  # the ledger lines `call` combines, counted one by one
    legacy: Legacy = Legacy()  # a summary's legacy rows, which its cost figures leave out


def _add(a: float | None, b: float | None) -> float | None:
    """The sum of the figures present; None when neither is."""
    if a is None:
        return b
    if b is None:
        return a
    total = a + b
    return round(total, 10) if isinstance(total, float) else total


def _add_figures(a: Figures, b: Figures) -> Figures:
    summed = {name: _add(getattr(a, name), getattr(b, name)) for name in (*_COUNTS, "cost_usd")}
    return Figures(calls=a.calls + b.calls, **summed)


def _add_differences(a: Difference | None, b: Difference | None) -> Difference | None:
    if a is None or b is None:
        return a or b
    return Difference(
        **{name: _add(getattr(a, name), getattr(b, name)) for name in Difference.model_fields}
    )


def _combine(key: str, rows: Iterable[ReportRow]) -> ReportRow:
    measured, estimated = Figures(), Figures()
    times: dict[str, int | None] = dict.fromkeys(_TIMES)
    sources: set[str] = set()
    difference: Difference | None = None
    for row in rows:
        measured = _add_figures(measured, row.measured)
        estimated = _add_figures(estimated, row.estimated)
        for name in _TIMES:
            times[name] = _add(times[name], getattr(row, name))  # type: ignore[assignment]
        sources.update(row.sources)
        difference = _add_differences(difference, row.difference)
    return ReportRow(
        key=key,
        measured=measured,
        estimated=estimated,
        sources=tuple(sorted(sources)),
        difference=difference,
        **times,
    )


def _difference(record: UsageRecord) -> Difference | None:
    """Gateway minus reported for each figure both have, None when none is."""
    reported = record.reported
    pairs = {
        "input_tokens": (record.input_tokens, reported.input_tokens if reported else None),
        "output_tokens": (record.output_tokens, reported.output_tokens if reported else None),
        "cost_usd": (
            record.cost.incremental_usd if record.cost else None,
            record.cost.reported_usd if record.cost else None,
        ),
    }
    fields: dict[str, float | int] = {}
    for name, (ours, theirs) in pairs.items():
        if ours is not None and theirs is not None:
            fields[name] = round(ours - theirs, 10)
            fields[f"reported_{name}"] = theirs
    return Difference(**fields) if fields else None


def _call_row(record: UsageRecord) -> ReportRow:
    figures = Figures(
        calls=1,
        input_tokens=record.input_tokens,
        output_tokens=record.output_tokens,
        cache_read_input_tokens=record.cache_read_input_tokens,
        cache_creation_input_tokens=record.cache_creation_input_tokens,
        cost_usd=record.cost.incremental_usd if record.cost else None,
    )
    estimated = record.usage_source == "estimated"
    return ReportRow(
        key="",
        measured=Figures() if estimated else figures,
        estimated=figures if estimated else Figures(),
        agent_ms=record.duration_ms,
        sources=(record.usage_source,),
        difference=_difference(record),
    )


def _time_row(**bucket: int) -> ReportRow:
    return ReportRow.model_validate(
        {"key": "", "measured": Figures(), "estimated": Figures(), **bucket}
    )


def _span_row(raw: dict) -> ReportRow | None:
    duration = raw.get("duration_ms")
    if not isinstance(duration, int):
        return None
    if raw.get("command"):
        return _time_row(checks_ms=duration)
    if raw.get("waited") == spans.SLOT:
        return _time_row(slot_wait_ms=duration)
    if raw.get("waited") == spans.USAGE_PAUSE:
        return _time_row(pause_wait_ms=duration)
    # The node's own span repeats its agent call, and no bucket takes it twice.
    return None


def _when(value: object) -> datetime | None:
    try:
        at = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def _group_key(entry: _Entry, group_by: str) -> str:
    if group_by == "day":
        return entry.at.date().isoformat() if entry.at else NONE
    return getattr(entry, group_by) or NONE


def _row_of(raw: dict) -> ReportRow:
    fields = {k: raw[k] for k in ReportRow.model_fields if k in raw and k != "key"}
    return ReportRow.model_validate({**fields, "key": ""})


def _summary_parts(raw: dict) -> list[dict]:
    """What a summary line contributes: one part per breakdown item, or, for a
    line written before breakdowns, its totals under the no-breakdown label."""
    items = raw.get("breakdown")
    if not items:
        label = NO_BREAKDOWN
        return [{"node": label, "role": label, "model": label, "row": _row_of(raw)}]
    return [
        {
            "node": item["node"],
            "role": item["role"],
            "model": item["model"],
            "runtime": item.get("runtime", ""),
            "usage_source": item.get("usage_source", ""),
            "row": _row_of(item),
        }
        for item in items
    ]


def _entries_in(lines: list[str], units: dict[str, StoredUnit]) -> list[_Entry]:
    """Every contribution the ledger's lines hold: calls (one per unit, node,
    round and session), spans that are a bucket of time, and summaries."""

    def meta(unit: str, change: str, repo: str) -> dict[str, str]:
        stored = units.get(unit)
        return {
            "unit": unit,
            "change": change or (stored.change if stored else unit.split("/")[0]),
            "repo": repo or (stored.repo if stored else ""),
        }

    entries = [
        _Entry(
            **meta(r.unit, r.change, r.repo),
            parts=tuple(parts),
            node=r.node,
            role=r.role or NONE,
            model=r.model or NONE,
            runtime=r.runtime,
            usage_source=r.usage_source,
            at=_when(r.at),
            row=_call_row(r),
            call=r,
        )
        for parts in grouped_records(lines)
        for r in [combine_records(parts)]
    ]
    for line in lines:
        try:
            raw = json.loads(line)
            kind = raw.get("kind")
            if kind == "span":
                row = _span_row(raw)
                if row is None:
                    continue
                parts = [{"node": raw.get("node") or NONE, "row": row}]
            elif kind == "summary":
                parts = _summary_parts(raw)
            else:
                continue
            found = [
                _Entry.model_validate(
                    {
                        **meta(
                            str(raw["unit"]), str(raw.get("change", "")), str(raw.get("repo", ""))
                        ),
                        "at": _when(raw.get("at")),
                        **part,
                    }
                )
                for part in parts
            ]
            if kind == "summary" and found and isinstance(raw.get("legacy"), dict):
                kept = Legacy.model_validate(raw["legacy"])
                found[0] = found[0].model_copy(update=dict(legacy=kept))
        except (ValueError, AttributeError, KeyError, TypeError, ValidationError):
            continue
        entries.extend(found)
    return entries


def _review_waits(unit: StoredUnit) -> list[_Entry]:
    """Each stretch the unit sat in review that a later state ended."""
    return [
        _Entry(
            unit=unit.id,
            change=unit.change,
            repo=unit.repo,
            at=start,
            row=_time_row(review_wait_ms=_ms(start, end)),
        )
        for state, start, end in _stretches(unit)
        if state == IN_REVIEW
    ]


def _finish(row: ReportRow, include_estimates: bool) -> ReportRow:
    if not include_estimates:
        return row
    return row.model_copy(update={"measured": _add_figures(row.measured, row.estimated)})


def _all_entries(ledger: Path, units: list[StoredUnit]) -> list[_Entry]:
    """The ledger's contributions, read once, and the review waits the store holds
    for the units the ledger knows."""
    entries = _entries_in(read_lines(ledger), {u.id: u for u in units})
    known = {e.unit for e in entries}
    # A summary that holds a unit's review wait already counts it.
    summarised = {e.unit for e in entries if e.row.review_wait_ms is not None}
    return entries + [
        wait for u in units if u.id in known - summarised for wait in _review_waits(u)
    ]


def build_report(
    ledger: Path,
    units: list[StoredUnit],
    *,
    group_by: str,
    since: datetime | None = None,
    change: str | None = None,
    unit: str | None = None,
    include_estimates: bool = False,
) -> Report:
    """The ledger's rows grouped by `group_by`, filtered by date, change or unit."""
    return _report_of(
        _all_entries(ledger, units),
        group_by=group_by,
        since=since,
        change=change,
        unit=unit,
        include_estimates=include_estimates,
    )


def build_context_report(
    ledger: Path,
    units: list[StoredUnit],
    *,
    since: datetime | None = None,
    change: str | None = None,
    unit: str | None = None,
) -> ContextReport:
    """How full the context window was, per step kind and per session."""
    floor = None if since is None else since if since.tzinfo else since.replace(tzinfo=UTC)
    calls = [
        (e, e.call)
        for e in _all_entries(ledger, units)
        if e.call is not None
        and (change is None or e.change == change)
        and (unit is None or e.unit == unit)
        and (floor is None or (e.at is not None and e.at >= floor))
    ]
    known = [(e, c) for e, c in calls if c.context is not None and c.context.used_end is not None]
    by_node: dict[str, list[UsageRecord]] = {}
    by_session: dict[str, list[tuple[datetime, int]]] = {}
    for entry, call in known:
        assert call.context is not None and call.context.used_end is not None
        by_node.setdefault(call.node, []).append(call)
        if call.session_id:
            by_session.setdefault(call.session_id, []).append(
                (entry.at or datetime.min.replace(tzinfo=UTC), call.context.used_end)
            )
    adders = sorted(
        (
            Adder(unit=c.unit, node=c.node, round=c.round, added=c.context.added)
            for _, c in known
            if c.context is not None and c.context.added is not None
        ),
        key=lambda a: -a.added,
    )
    return ContextReport(
        steps=tuple(_step_context(node, group) for node, group in sorted(by_node.items())),
        sessions=tuple(
            SessionContext(session_id=sid, fills=tuple(fill for _, fill in sorted(rows)))
            for sid, rows in sorted(by_session.items())
        ),
        biggest=tuple(adders[:BIGGEST]),
        unknown_calls=len(calls) - len(known),
    )


def _step_context(node: str, group: list[UsageRecord]) -> StepContext:
    contexts = [c.context for c in group if c.context is not None]
    added = sorted(c.added for c in contexts if c.added is not None)
    ends = [c.used_end for c in contexts if c.used_end is not None]
    windows = [c.max for c in contexts if c.max is not None]
    peaks = [c.peak for c in contexts if c.peak is not None]
    peak = max(peaks, default=None)
    return StepContext(
        node=node,
        calls=len(contexts),
        mean_added=sum(added) / len(added) if added else 0.0,
        p90_added=added[math.ceil(0.9 * len(added)) - 1] if added else 0.0,
        compactions=sum(c.compactions for c in contexts),
        used_end=round(sum(ends) / len(ends)),
        max=max(windows, default=None),
        peak=peak if peak is not None and peak > max(ends) else None,
    )


def _tokens(count: float) -> str:
    return f"{round(count / 1000)}k"


def render_context(report: ContextReport) -> str:
    """The context report as the table `abk report --context` prints."""
    steps = [["step", "calls", "mean added", "p90 added", "compactions", "end fill", "peak"]]
    for step in report.steps:
        fill = _tokens(step.used_end) + (f" / {_tokens(step.max)}" if step.max else "")
        steps.append(
            [
                step.node,
                str(step.calls),
                _tokens(step.mean_added),
                _tokens(step.p90_added),
                str(step.compactions),
                fill,
                f"peak {_tokens(step.peak)}" if step.peak is not None else "",
            ]
        )
    out = [*_aligned(steps)]
    if report.sessions:
        out += ["", "session fill after each step"]
        out += [
            f"{s.session_id}  " + " -> ".join(_tokens(fill) for fill in s.fills)
            for s in report.sessions
        ]
    if report.biggest:
        out += ["", "steps that added the most"]
        out += [f"{a.unit} {a.node} round {a.round}  +{_tokens(a.added)}" for a in report.biggest]
    out += ["", f"{report.unknown_calls} unknown (no context figures, left out of the means)"]
    return "\n".join(out)


def _report_of(
    entries: list[_Entry],
    *,
    group_by: str,
    since: datetime | None = None,
    change: str | None = None,
    unit: str | None = None,
    include_estimates: bool = False,
) -> Report:
    if group_by not in GROUPINGS:
        raise ValueError(f"cannot group by {group_by!r}; choose from {', '.join(GROUPINGS)}")
    if change is not None:
        entries = [e for e in entries if e.change == change]
    if unit is not None:
        entries = [e for e in entries if e.unit == unit]
    scoped = entries
    if since is not None:
        floor = since if since.tzinfo else since.replace(tzinfo=UTC)
        entries = [e for e in entries if e.at is not None and e.at >= floor]

    groups: dict[str, list[ReportRow]] = {}
    overhead: dict[str, list[ReportRow]] = {}
    for entry in entries:
        # An agent call with no unit is pipeline overhead: the by-unit view lists it by node.
        if group_by == "unit" and not entry.unit and entry.call is not None:
            overhead.setdefault(entry.node, []).append(entry.row)
        else:
            groups.setdefault(_group_key(entry, group_by), []).append(entry.row)
    rows = tuple(_finish(_combine(key, groups[key]), include_estimates) for key in sorted(groups))
    overheads = tuple(
        _finish(_combine(node, overhead[node]), include_estimates) for node in sorted(overhead)
    )
    total = _finish(_combine("total", (e.row for e in entries)), include_estimates)
    calls = [e.call for e in entries if e.call is not None]
    # A session is judged on all its calls, so a date that cuts it does not flag it.
    live = {c.session_id for c in calls if c.session_id}
    whole = [e.call for e in scoped if e.call is not None and e.call.session_id in live]
    return Report(
        group_by=group_by,
        rows=rows,
        total=total,
        overhead=overheads,
        sessions=_sessions(whole),
        legacy=_legacy(entries),
        unknown_calls=sum(
            1
            for e in entries
            for p in e.parts
            if p.cost is not None and p.cost.basis == CostBasis.UNKNOWN
        ),
    )


def _sessions(calls: list[UsageRecord]) -> tuple[SessionRow, ...]:
    """Each session's increments summed beside its final cumulative figure, flagged when
    they do not agree."""
    by_session: dict[str, list[UsageRecord]] = {}
    for call in calls:
        if call.session_id and call.cost is not None and call.cost.basis != CostBasis.LEGACY:
            by_session.setdefault(call.session_id, []).append(call)
    rows = []
    for session_id, parts in sorted(by_session.items()):
        increments = [
            p.cost.incremental_usd for p in parts if p.cost and p.cost.incremental_usd is not None
        ]
        finals = [
            (p.at, p.cost.cumulative_usd)
            for p in parts
            if p.cost and p.cost.cumulative_usd is not None
        ]
        incremental = sum(increments) if increments else None
        cumulative = max(finals)[1] if finals else None
        flagged = (
            cumulative is not None and abs((incremental or 0.0) - cumulative) > SESSION_TOLERANCE
        )
        rows.append(
            SessionRow(
                session_id=session_id,
                incremental_usd=None if incremental is None else round(incremental, 10),
                cumulative_usd=cumulative,
                flagged=flagged,
            )
        )
    return tuple(rows)


def _legacy(entries: list[_Entry]) -> Legacy:
    """The older flat figures: those of calls still in the ledger, whatever basis a later call
    folded into their record gave it, and those a summary kept when it replaced the calls."""
    rows = [
        LegacyRow(unit=p.unit, node=p.node, legacy_usd=p.cost.legacy_usd)
        for e in entries
        for p in e.parts
        if p.cost is not None and p.cost.legacy_usd is not None
    ]
    rows += [row for e in entries for row in e.legacy.rows]
    rows.sort(key=lambda r: (r.unit, r.node, r.legacy_usd))
    total = round(sum(r.legacy_usd for r in rows), 10) if rows else None
    return Legacy(count=len(rows), total_usd=total, rows=tuple(rows))


_HEADINGS = (
    "calls",
    "input",
    "output",
    "cache read",
    "cache write",
    "cost",
    "agent",
    "checks",
    "slot wait",
    "pause wait",
    "review wait",
    "estimated in",
    "estimated cost",
    "source",
)


def _count(value: float | None) -> str:
    return "-" if value is None else f"{value:.0f}"


def _cost(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}"


def _seconds(ms: int | None) -> str:
    return "-" if ms is None else f"{ms / 1000:.1f}s"


def _differs(row: ReportRow) -> bool:
    d = row.difference
    if d is None:
        return False
    for gap, reported in (
        (d.input_tokens, d.reported_input_tokens),
        (d.output_tokens, d.reported_output_tokens),
        (d.cost_usd, d.reported_cost_usd),
    ):
        if gap is not None and reported and abs(gap) / reported > LARGE_DIFFERENCE:
            return True
    return False


def _cells(row: ReportRow) -> list[str]:
    m = row.measured
    return [
        row.key,
        str(m.calls),
        _count(m.input_tokens),
        _count(m.output_tokens),
        _count(m.cache_read_input_tokens),
        _count(m.cache_creation_input_tokens),
        _cost(m.cost_usd),
        _seconds(row.agent_ms),
        _seconds(row.checks_ms),
        _seconds(row.slot_wait_ms),
        _seconds(row.pause_wait_ms),
        _seconds(row.review_wait_ms),
        _count(row.estimated.input_tokens),
        _cost(row.estimated.cost_usd),
        (",".join(row.sources) or "-") + (" (differs)" if _differs(row) else ""),
    ]


def _aligned(table: list[list[str]]) -> list[str]:
    widths = [max(len(line[i]) for line in table) for i in range(len(table[0]))]
    return [
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        for line in table
    ]


def render_table(report: Report) -> str:
    table = [[report.group_by, *_HEADINGS], *(_cells(r) for r in (*report.rows, report.total))]
    lines = _aligned(table)
    if report.overhead:
        lines += ["", "pipeline overhead", *_aligned([_cells(r) for r in report.overhead])]
    if report.sessions:
        sessions = [["session", "increments", "cumulative", ""]] + [
            [
                s.session_id,
                _cost(s.incremental_usd),
                _cost(s.cumulative_usd),
                "FLAGGED: increments do not add up" if s.flagged else "",
            ]
            for s in report.sessions
        ]
        lines += ["", *_aligned(sessions)]
    if report.legacy.count:
        lines += [
            "",
            f"legacy rows: {report.legacy.count}, {_cost(report.legacy.total_usd)} USD "
            "(older flat figures, not in the cost above)",
            *(f"  {r.unit} {r.node} {_cost(r.legacy_usd)}" for r in report.legacy.rows),
        ]
    if report.unknown_calls:
        lines += ["", f"calls with an unknown cost: {report.unknown_calls} (not in the cost above)"]
    return "\n".join(lines)


def render_json(report: Report | WaitReport) -> str:
    return report.model_dump_json(indent=2)


def _page(by_change: Report, by_unit: Report) -> str:
    lines = [
        "# Unit cost",
        "",
        "Measured figures from the usage ledger; estimates are left out "
        "(`abk report --include-estimates`).",
        "",
        "## By change",
        "",
        "| change | calls | input | output | cost (USD) | agent time |",
        "|---|---|---|---|---|---|",
    ]
    for r in by_change.rows:
        m = r.measured
        lines.append(
            f"| {r.key} | {m.calls} | {_count(m.input_tokens)} | {_count(m.output_tokens)} "
            f"| {_cost(m.cost_usd)} | {_seconds(r.agent_ms)} |"
        )
    lines += [
        "",
        f"## Most expensive units (top {TOP_UNITS})",
        "",
        "| unit | calls | cost (USD) | agent time |",
        "|---|---|---|---|",
    ]
    ranked = sorted(by_unit.rows, key=lambda r: r.measured.cost_usd or 0.0, reverse=True)
    for r in ranked[:TOP_UNITS]:
        lines.append(
            f"| {r.key} | {r.measured.calls} | {_cost(r.measured.cost_usd)} "
            f"| {_seconds(r.agent_ms)} |"
        )
    return "\n".join(lines) + "\n"


def write_page(units: list[StoredUnit], ledger: Path, out: Path) -> None:
    """Rewrite the summary page at `out` (per-change totals and the most
    expensive units); raises `OSError` when it cannot."""
    entries = _all_entries(ledger, units)
    page = _page(
        _report_of(entries, group_by="change"),
        _report_of(entries, group_by="unit"),
    )
    if out.exists() and out.read_text() == page:
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)


def _breakdown(group: list[_Entry]) -> list[dict]:
    """The group's contributions summed per node, role, model and usage source,
    ordered by that key. Waits and checks carry no role, model or source, so
    they sit in an item of their own for the node, which takes the node's runtime;
    an item takes the least runtime among its entries, and a node's runtime is
    the least among all its entries."""
    keyed: dict[tuple[str, str, str, str], list[_Entry]] = {}
    runtimes: dict[str, str] = {}
    for entry in group:
        key = (entry.node, entry.role, entry.model, entry.usage_source)
        keyed.setdefault(key, []).append(entry)
        if entry.runtime:
            runtimes[entry.node] = min(entry.runtime, runtimes.get(entry.node, entry.runtime))
    return [
        {
            "node": node,
            "role": role,
            "model": model,
            "runtime": min(
                (e.runtime for e in keyed[key] if e.runtime), default=runtimes.get(node, "")
            ),
            "usage_source": source,
            **_combine("", (e.row for e in keyed[key])).model_dump(exclude={"key"}),
        }
        for key in sorted(keyed)
        for node, role, model, source in [key]
    ]


def _summary_bases(lines: list[str]) -> dict[str, str]:
    """The `cost_basis` mark of each unit's summary lines that carry one."""
    found: dict[str, str] = {}
    for line in lines:
        try:
            raw = json.loads(line)
            if raw.get("kind") == "summary" and isinstance(raw.get("cost_basis"), str):
                found[str(raw["unit"])] = raw["cost_basis"]
        except (ValueError, AttributeError, KeyError):
            continue
    return found


_WAIT_CAUSES = (
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
# The reasons in the decision log that say a unit could start: what `mark_ready` stamps.
_READY = frozenset({WaitReason.SLOT, WaitReason.READY, WaitReason.USAGE_PAUSE})


def _kind_lines(lines: list[str], kind: str) -> Iterable[dict]:
    for line in lines:
        try:
            raw = json.loads(line)
        except ValueError:
            continue
        if isinstance(raw, dict) and raw.get("kind") == kind:
            yield raw


def _round_spans(lines: list[str]) -> dict[str, list[tuple[datetime, datetime]]]:
    """The review-round spans (those with a cause) of each unit, as `(started, ended)`."""
    found: dict[str, list[tuple[datetime, datetime]]] = {}
    for raw in _kind_lines(lines, "span"):
        started, ended = _when(raw.get("started")), _when(raw.get("ended"))
        if raw.get("cause") and raw.get("unit") and started and ended:
            found.setdefault(str(raw["unit"]), []).append((started, ended))
    return found


def _decided_ready(decisions: Path) -> dict[str, datetime]:
    """When each unit's first wait that said it could start began, for a unit that
    carries no `ready_at`."""
    found: dict[str, datetime] = {}
    try:
        lines = decisions.read_text().splitlines()
    except OSError:
        return found
    for line in lines:
        try:
            raw = json.loads(line)
            at = _when(raw["at"])
            if raw["reason"] in _READY and at is not None:
                found.setdefault(str(raw["unit"]), at)
        except (ValueError, KeyError, TypeError):
            continue
    return found


def _stretches(unit: StoredUnit) -> list[tuple[str, datetime, datetime]]:
    """Each stretch of the unit's history that a later entry ended."""
    found = []
    for entry, following in zip(unit.history, unit.history[1:], strict=False):
        start, end = _when(entry.get("at")), _when(following.get("at"))
        if start is not None and end is not None:
            found.append((str(entry.get("state")), start, end))
    return found


def _ms(start: datetime, end: datetime) -> int:
    return int((end - start).total_seconds() * 1000)


def _round_ms_within(
    unit: StoredUnit, rounds: Sequence[tuple[datetime, datetime]], start: datetime, end: datetime
) -> int:
    """The time of the rounds that began after the unit first entered review that lies in
    `start`..`end`. A round runs while the unit is running or planned, never in review, and
    one before the first review is that build's own work."""
    entered = unit.review_requested_at
    if entered is None:
        return 0
    return sum(
        max(0, _ms(max(begun, start), min(ended, end)))
        for begun, ended in rounds
        if begun >= entered
    )


class _ReviewSplit(Frozen):
    """A unit's time in review stretches: a person's and the checks', which sum to it, and
    beside them the time of the rounds after the first review entry, which lie outside it."""

    stretch: int
    person: int
    checks: int
    round: int


def _review_split(unit: StoredUnit, rounds: Sequence[tuple[datetime, datetime]]) -> _ReviewSplit:
    """A person's time runs from entering review to `first_human_activity_at`, clipped to
    the stretches, or is all of them when nobody answered; the checks are the rest."""
    stretches = _stretches(unit)
    stretch = sum(_ms(s, e) for state, s, e in stretches if state == IN_REVIEW)
    started, answered = unit.review_requested_at, unit.first_human_activity_at
    person = stretch
    if answered is not None and started is not None:
        person = min(stretch, max(0, _ms(started, answered)))
    taken = sum(
        _round_ms_within(unit, rounds, s, e)
        for state, s, e in stretches
        if state in (PLANNED, RUNNING)
    )
    return _ReviewSplit(stretch=stretch, person=person, checks=stretch - person, round=taken)


# The figure that holds the whole time in each state.
_STATE_FIGURES = {PLANNED: "planned_ms", RUNNING: "running_ms", IN_REVIEW: "in_review_ms"}


def _unit_waits(
    unit: StoredUnit,
    ready: datetime | None,
    recorded: dict[str, list[tuple[datetime | None, int]]],
    rounds: Sequence[tuple[datetime, datetime]],
) -> list[tuple[datetime, str, int]]:
    """The unit's wall time as `(when, cause, ms)`, and its time in each state whole. A
    running stretch holds the rounds after the first review, then the unit's pauses, checks
    and agent calls, in that order, and the rest is other; a round's own agent calls are
    taken out of the running time again, so the round and the calls overlap. A planned
    stretch with no ready stamp is not divided into blocked and ready, but its rounds are
    told. A review stretch is a person's time up to their answer and the checks' after it."""
    found: list[tuple[datetime | None, str, int]] = []
    running = 0
    running_at = None
    for state, start, end in _stretches(unit):
        taken = _round_ms_within(unit, rounds, start, end) if state in (PLANNED, RUNNING) else 0
        found.append((start, "in_review_round_ms", taken))
        if state in _STATE_FIGURES:
            found.append((start, _STATE_FIGURES[state], _ms(start, end)))
        if state == PLANNED and ready:
            split = min(max(ready, start), end)
            waiting = _ms(split, end)
            found += [
                (start, "planned_blocked_ms", _ms(start, split) - max(0, taken - waiting)),
                (split, "planned_ready_ms", waiting - min(taken, waiting)),
            ]
        elif state == RUNNING:
            running, running_at = running + _ms(start, end) - taken, running_at or start
        elif state in (FAILED, HELD):
            found.append((start, "failed_ms", _ms(start, end)))
    first = _when(unit.history[0].get("at")) if unit.history else None
    for cause in ("paused_ms", "running_checks_ms", "running_agent_ms"):
        for at, ms in recorded.get(cause, []):
            taken = min(ms, running)
            running -= taken
            found.append((at or first, cause, taken))
    found.append((running_at, "running_other_ms", running))
    split = _review_split(unit, rounds)
    # What a person did not hold the review for is the checks'.
    found += [
        (unit.review_requested_at, "in_review_person_ms", split.person),
        (unit.review_requested_at, "running_checks_ms", split.stretch - split.person),
    ]
    return [(at, cause, ms) for at, cause, ms in found if at is not None and ms > 0]


def _wait_row(key: str, sums: dict[str, int]) -> WaitRow:
    caused = [ms for cause, ms in sums.items() if cause in _WAIT_CAUSES]
    return WaitRow(key=key, wall_ms=sum(caused) if caused else None, **sums)


def _idle_hours(lines: list[str]) -> IdleHours:
    """Each sample stands for the time to the next; the last one stands for none."""
    found = []
    for raw in _kind_lines(lines, spans.Sample.model_fields["kind"].default):
        try:
            sample = spans.Sample.model_validate(raw)
        except ValidationError:
            continue
        if (at := _when(sample.at)) is not None:
            found.append((at, sample))
    found.sort(key=lambda pair: pair[0])
    hours = dict.fromkeys(("observed", "idle", "full", "room"), 0.0)
    for (at, sample), (following, _) in zip(found, found[1:], strict=False):
        span = (following - at).total_seconds() / 3600
        hours["observed"] += span
        if sample.running == 0:
            hours["idle"] += span
            full = sample.running + sample.in_review >= sample.limit
            hours["full" if full else "room"] += span
    return IdleHours(
        observed_h=hours["observed"],
        idle_h=hours["idle"],
        queue_full_h=hours["full"],
        room_h=hours["room"],
    )


def _estimate_ratios(units: list[StoredUnit]) -> tuple[EstimateRatio, ...]:
    kinds: dict[Kind, list[StoredUnit]] = {}
    for unit in units:
        if measured(unit):
            kinds.setdefault(kind_of(unit), []).append(unit)
    return tuple(
        EstimateRatio(
            kind=kind.label,
            ratio=sum(u.actual_lines or 0 for u in group) / sum(u.estimated_lines for u in group),
            units=len(group),
        )
        for kind, group in sorted(kinds.items(), key=lambda pair: pair[0].label)
    )


def build_wait_report(
    ledger: Path,
    decisions: Path,
    units: list[StoredUnit],
    *,
    group_by: str = "unit",
) -> WaitReport:
    """Each unit's wall time by cause, from its history, the ledger's spans and the
    decision log, and the idle hours from the ledger's samples."""
    if group_by not in WAIT_GROUPINGS:
        raise ValueError(f"cannot group by {group_by!r}; choose from {', '.join(WAIT_GROUPINGS)}")
    lines = read_lines(ledger)
    entries = _entries_in(lines, {u.id: u for u in units})
    rounds = _round_spans(lines)
    ready = _decided_ready(decisions)
    groups: dict[str, dict[str, int]] = {u.id: {} for u in units} if group_by == "unit" else {}
    everything: dict[str, int] = {}
    for unit in units:
        recorded: dict[str, list[tuple[datetime | None, int]]] = {}
        for entry in entries:
            if entry.unit == unit.id:
                for cause, ms in (
                    ("running_agent_ms", entry.row.agent_ms),
                    ("running_checks_ms", entry.row.checks_ms),
                    ("paused_ms", entry.row.pause_wait_ms),
                ):
                    if ms:
                        recorded.setdefault(cause, []).append((entry.at, ms))
        stamp = _when(unit.ready_at) if unit.ready_at else ready.get(unit.id)
        for at, cause, ms in _unit_waits(unit, stamp, recorded, rounds.get(unit.id, [])):
            key = unit.id if group_by == "unit" else at.date().isoformat()
            sums = groups.setdefault(key, {})
            sums[cause] = sums.get(cause, 0) + ms
            everything[cause] = everything.get(cause, 0) + ms
    return WaitReport(
        group_by=group_by,
        rows=tuple(_wait_row(key, groups[key]) for key in sorted(groups)),
        total=_wait_row("total", everything),
        idle=_idle_hours(lines),
        estimates=_estimate_ratios(units),
    )


def _hours(ms: int | None) -> str:
    return "-" if ms is None else f"{ms / 3_600_000:.1f}"


def render_waits(report: WaitReport) -> str:
    headings = ("wall", *(name.removesuffix("_ms").replace("_", " ") for name in _WAIT_CAUSES))
    cells = [
        [row.key, *(_hours(x) for x in (row.wall_ms, *(getattr(row, n) for n in _WAIT_CAUSES)))]
        for row in (*report.rows, report.total)
    ]
    total = report.total
    lines = [
        *_aligned([[report.group_by, *headings], *cells]),
        "",
        f"hours: planned {_hours(total.planned_ms)}, in review {_hours(total.in_review_ms)}, "
        f"running {_hours(total.running_ms)} (agent {_hours(total.running_agent_ms)})",
    ]
    idle = report.idle
    if idle.observed_h:
        lines.append(
            f"nothing ran for {idle.idle_h:.0f} of {idle.observed_h:.0f} hours: "
            f"{idle.queue_full_h:.0f} with a full queue, {idle.room_h:.0f} with room"
        )
    lines += [f"estimate {e.kind}: {e.ratio:.2f} ({e.units} units)" for e in report.estimates]
    return "\n".join(lines)


def _review_entry(unit: StoredUnit, rounds: Sequence[tuple[datetime, datetime]]) -> list[_Entry]:
    """The unit's time in review as a person's, the rounds' and the checks'."""
    if not _review_waits(unit):
        return []
    split = _review_split(unit, rounds)
    return [
        _Entry(
            unit=unit.id,
            change=unit.change,
            repo=unit.repo,
            row=_time_row(
                review_wait_ms=split.stretch,
                review_person_ms=split.person,
                review_round_ms=split.round,
                review_checks_ms=split.checks,
            ),
        )
    ]


def roll_up_change(ledger: Path, change: str, units: Sequence[StoredUnit] = ()) -> None:
    """Replace the change's detail lines with one `summary` line per unit.

    Holds the ledger's lock from the read to the swap, so a line appended
    meanwhile waits and lands in the new file rather than being dropped."""
    if not ledger.exists():
        return
    with ledger_lock(ledger):
        lines = read_lines(ledger)
        marked = _summary_bases(lines)
        by_unit: dict[str, list[_Entry]] = {}
        for entry in _entries_in(lines, {}):
            if entry.change == change:
                by_unit.setdefault(entry.unit, []).append(entry)
        stored = {u.id: u for u in units}
        rounds = _round_spans(lines)
        summaries = []
        for unit, group in sorted(by_unit.items()):
            # A summary of an earlier roll-up already holds the unit's review wait.
            if unit in stored and all(e.row.review_wait_ms is None for e in group):
                group += _review_entry(stored[unit], rounds.get(unit, []))
            stamps = [e.at for e in group if e.at is not None]
            breakdown = _breakdown(group)
            total = _combine(unit, (e.row for e in group))
            if _combine(unit, (_row_of(i) for i in breakdown)) != total:
                raise ValueError(f"the breakdown of {unit} does not sum to its totals")
            legacy = _legacy(group)
            summaries.append(
                {
                    "kind": "summary",
                    "at": (max(stamps) if stamps else datetime.now(UTC)).isoformat(),
                    "unit": unit,
                    "change": change,
                    "repo": next((e.repo for e in group if e.repo), ""),
                    # Summed from incremental figures, unless it carries an older summary's mark.
                    "cost_basis": marked.get(unit, str(CostBasis.REPORTED)),
                    **total.model_dump(exclude={"key"}),
                    "breakdown": breakdown,
                    **(dict(legacy=legacy.model_dump()) if legacy.count else {}),
                }
            )

        kept = []
        for line in lines:
            try:
                raw = json.loads(line)
                ours = raw.get("kind") != "metric" and (
                    (raw.get("change") or str(raw["unit"]).split("/")[0]) == change
                )
            except (ValueError, AttributeError, KeyError):
                ours = False
            if line and not ours:
                kept.append(line)
        kept += [json.dumps(s) for s in summaries]
        atomic_write_text(ledger, "".join(f"{line}\n" for line in kept))
