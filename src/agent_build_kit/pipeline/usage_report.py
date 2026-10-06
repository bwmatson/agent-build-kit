"""Reads the usage ledger back as rows, for `abk report`, the summary page and
the archive roll-up.

The reader keeps one record per unit, node, round and session, tolerates
half-written lines and fields it does not know, joins unit metadata from the
store, and groups by unit, change, node, role, model, repository or day.
Estimated figures sit in their own column and are left out of totals unless
asked for; a figure never recorded is `None`, not zero.

A change's detail lines are rolled up into one `summary` line per unit when it
is archived. A summary no longer knows its calls' nodes, roles or models, so
grouped by those it reads as `(summary)`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.usage_ledger import UsageRecord, read_ledger

GROUPINGS = ("unit", "change", "node", "role", "model", "repo", "day")

NONE = "(none)"
SUMMARY = "(summary)"
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


class Report(Frozen):
    group_by: str
    rows: tuple[ReportRow, ...]
    total: ReportRow


class _Entry(Frozen):
    """One contribution to the report — a call, a span, a summary or a review
    wait — with what it can be grouped by."""

    unit: str
    change: str
    repo: str
    node: str = NONE
    role: str = NONE
    model: str = NONE
    at: datetime | None = None
    row: ReportRow


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
        "cost_usd": (record.cost_usd, record.reported_cost_usd),
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
        cost_usd=record.cost_usd,
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
    if raw.get("waited") == "slot":
        return _time_row(slot_wait_ms=duration)
    if raw.get("waited") == "usage_pause":
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


def _ledger_entries(ledger: Path, units: dict[str, StoredUnit]) -> list[_Entry]:
    """Every contribution the ledger holds: calls (one per unit, node, round and
    session), spans that are a bucket of time, and summaries."""

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
            at=_when(r.at),
            row=_call_row(r),
        )
        for r in read_ledger(ledger)
    ]
    try:
        lines = ledger.read_text().splitlines()
    except FileNotFoundError:
        return entries
    for line in lines:
        try:
            raw = json.loads(line)
            kind = raw.get("kind")
            if kind == "span":
                row = _span_row(raw)
                if row is None:
                    continue
                node, role, model = raw.get("node") or NONE, NONE, NONE
            elif kind == "summary":
                fields = {k: raw[k] for k in ReportRow.model_fields if k in raw and k != "key"}
                row = ReportRow.model_validate({**fields, "key": ""})
                node = role = model = SUMMARY
            else:
                continue
            entries.append(
                _Entry(
                    **meta(str(raw["unit"]), str(raw.get("change", "")), str(raw.get("repo", ""))),
                    node=node,
                    role=role,
                    model=model,
                    at=_when(raw.get("at")),
                    row=row,
                )
            )
        except (ValueError, AttributeError, KeyError, TypeError, ValidationError):
            continue
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
    if group_by not in GROUPINGS:
        raise ValueError(f"cannot group by {group_by!r}; choose from {', '.join(GROUPINGS)}")
    entries = _ledger_entries(ledger, {u.id: u for u in units})
    # Review waits come from the store, for the units the ledger knows.
    known = {e.unit for e in entries}
    entries += [wait for u in units if u.id in known for wait in _review_waits(u)]
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
    return Report(group_by=group_by, rows=rows, total=total)


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


def render_table(report: Report) -> str:
    table = [[report.group_by, *_HEADINGS], *(_cells(r) for r in (*report.rows, report.total))]
    widths = [max(len(line[i]) for line in table) for i in range(len(table[0]))]
    return "\n".join(
        "  ".join(cell.ljust(width) for cell, width in zip(line, widths, strict=True)).rstrip()
        for line in table
    )


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
    page = _page(
        build_report(ledger, units, group_by="change"),
        build_report(ledger, units, group_by="unit"),
    )
    if out.exists() and out.read_text() == page:
        return
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page)


def roll_up_change(ledger: Path, change: str) -> None:
    """Replace the change's detail lines with one `summary` line per unit."""
    if not ledger.exists():
        return
    by_unit: dict[str, list[_Entry]] = {}
    for entry in _ledger_entries(ledger, {}):
        if entry.change == change:
            by_unit.setdefault(entry.unit, []).append(entry)
    summaries = []
    for unit, group in sorted(by_unit.items()):
        stamps = [e.at for e in group if e.at is not None]
        summaries.append(
            {
                "kind": "summary",
                "at": (max(stamps) if stamps else datetime.now(UTC)).isoformat(),
                "unit": unit,
                "change": change,
                "repo": next((e.repo for e in group if e.repo), ""),
                **_combine(unit, (e.row for e in group)).model_dump(exclude={"key"}),
            }
        )

    kept = []
    for line in ledger.read_text().splitlines():
        try:
            raw = json.loads(line)
            ours = (raw.get("change") or str(raw["unit"]).split("/")[0]) == change
        except (ValueError, AttributeError, KeyError):
            ours = False
        if line and not ours:
            kept.append(line)
    kept += [json.dumps(s) for s in summaries]
    scratch = ledger.with_name(ledger.name + ".tmp")
    scratch.write_text("".join(f"{line}\n" for line in kept))
    os.replace(scratch, ledger)
