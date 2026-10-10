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
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.usage_ledger import (
    CostBasis,
    UsageRecord,
    ledger_lock,
    read_lines,
    records_in,
)

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
_TIMES = ("agent_ms", "checks_ms", "slot_wait_ms", "pause_wait_ms", "review_wait_ms")


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
    sessions: tuple[SessionRow, ...] = ()
    legacy: Legacy = Legacy()
    unknown_calls: int = 0  # calls whose incremental cost could not be known


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
            node=r.node,
            role=r.role or NONE,
            model=r.model or NONE,
            runtime=r.runtime,
            usage_source=r.usage_source,
            at=_when(r.at),
            row=_call_row(r),
            call=r,
        )
        for r in records_in(lines)
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
        except (ValueError, AttributeError, KeyError, TypeError, ValidationError):
            continue
        entries.extend(found)
    return entries


def _review_waits(unit: StoredUnit) -> list[_Entry]:
    """Each stretch the unit sat in review that a later state ended."""
    waits = []
    for entry, following in zip(unit.history, unit.history[1:], strict=False):
        if entry.get("state") != "in_review":
            continue
        start, end = _when(entry.get("at")), _when(following.get("at"))
        if start is None or end is None:
            continue
        waits.append(
            _Entry(
                unit=unit.id,
                change=unit.change,
                repo=unit.repo,
                at=start,
                row=_time_row(review_wait_ms=int((end - start).total_seconds() * 1000)),
            )
        )
    return waits


def _finish(row: ReportRow, include_estimates: bool) -> ReportRow:
    if not include_estimates:
        return row
    return row.model_copy(update={"measured": _add_figures(row.measured, row.estimated)})


def _all_entries(ledger: Path, units: list[StoredUnit]) -> list[_Entry]:
    """The ledger's contributions, read once, and the review waits the store holds
    for the units the ledger knows."""
    entries = _entries_in(read_lines(ledger), {u.id: u for u in units})
    known = {e.unit for e in entries}
    return entries + [wait for u in units if u.id in known for wait in _review_waits(u)]


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
    if since is not None:
        floor = since if since.tzinfo else since.replace(tzinfo=UTC)
        entries = [e for e in entries if e.at is not None and e.at >= floor]
    if change is not None:
        entries = [e for e in entries if e.change == change]
    if unit is not None:
        entries = [e for e in entries if e.unit == unit]

    groups: dict[str, list[ReportRow]] = {}
    for entry in entries:
        groups.setdefault(_group_key(entry, group_by), []).append(entry.row)
    rows = tuple(_finish(_combine(key, groups[key]), include_estimates) for key in sorted(groups))
    total = _finish(_combine("total", (e.row for e in entries)), include_estimates)
    calls = [e.call for e in entries if e.call is not None]
    return Report(
        group_by=group_by,
        rows=rows,
        total=total,
        sessions=_sessions(calls),
        legacy=_legacy(calls),
        unknown_calls=sum(
            1 for c in calls if c.cost is not None and c.cost.basis == CostBasis.UNKNOWN
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
        increments = [p.cost.incremental_usd for p in parts if p.cost and p.cost.incremental_usd]
        finals = [(p.at, p.cost.cumulative_usd) for p in parts if p.cost and p.cost.cumulative_usd]
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


def _legacy(calls: list[UsageRecord]) -> Legacy:
    rows = tuple(
        LegacyRow(unit=c.unit, node=c.node, legacy_usd=c.cost.legacy_usd)
        for c in calls
        if c.cost is not None and c.cost.basis == CostBasis.LEGACY and c.cost.legacy_usd is not None
    )
    total = round(sum(r.legacy_usd for r in rows), 10) if rows else None
    return Legacy(count=len(rows), total_usd=total, rows=rows)


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


def render_json(report: Report) -> str:
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


def roll_up_change(ledger: Path, change: str) -> None:
    """Replace the change's detail lines with one `summary` line per unit.

    Holds the ledger's lock from the read to the swap, so a line appended
    meanwhile waits and lands in the new file rather than being dropped."""
    if not ledger.exists():
        return
    with ledger_lock(ledger):
        lines = read_lines(ledger)
        by_unit: dict[str, list[_Entry]] = {}
        for entry in _entries_in(lines, {}):
            if entry.change == change:
                by_unit.setdefault(entry.unit, []).append(entry)
        summaries = []
        for unit, group in sorted(by_unit.items()):
            stamps = [e.at for e in group if e.at is not None]
            breakdown = _breakdown(group)
            total = _combine(unit, (e.row for e in group))
            if _combine(unit, (_row_of(i) for i in breakdown)) != total:
                raise ValueError(f"the breakdown of {unit} does not sum to its totals")
            summaries.append(
                {
                    "kind": "summary",
                    "at": (max(stamps) if stamps else datetime.now(UTC)).isoformat(),
                    "unit": unit,
                    "change": change,
                    "repo": next((e.repo for e in group if e.repo), ""),
                    **total.model_dump(exclude={"key"}),
                    "breakdown": breakdown,
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
        scratch = ledger.with_name(ledger.name + ".tmp")
        scratch.write_text("".join(f"{line}\n" for line in kept))
        os.replace(scratch, ledger)
