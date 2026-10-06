"""Reads the usage ledger back as rows, for `abk report`, the summary page and
the archive roll-up.

The reader keeps one record per unit, node, round and session, tolerates
half-written lines and fields it does not know, joins unit metadata from the
store, and groups by unit, change, node, role, model, repository or day.
Estimated figures sit in their own column and are left out of totals unless
asked for; a figure never recorded is `None`, not zero.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import StoredUnit

GROUPINGS = ("unit", "change", "node", "role", "model", "repo", "day")


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
    raise NotImplementedError


def render_table(report: Report) -> str:
    raise NotImplementedError


def render_json(report: Report) -> str:
    raise NotImplementedError


def write_page(units: list[StoredUnit], ledger: Path, out: Path) -> None:
    """Rewrite the summary page at `out` (per-change totals and the most
    expensive units); raises `OSError` when it cannot."""
    raise NotImplementedError


def roll_up_change(ledger: Path, change: str) -> None:
    """Replace the change's detail lines with one `summary` line per unit."""
    raise NotImplementedError
