"""One record per agent call, appended to `<state_dir>/usage-ledger.jsonl`.

Best-effort: a write that fails is dropped and reported once, and never
affects a run. The reader keeps the last record per unit, node and
round, adding a resumed call's figures to the call it resumed; a call with
no session id stays a record of its own.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from agent_build_kit import config, telemetry
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.usage import Usage, UsageSource

LEDGER_NAME = "usage-ledger.jsonl"

# What has been reported this process, so that many units failing the same way
# say it once; guarded because units run on threads.
_told: set[str] = set()
_told_lock = threading.Lock()


class CostBasis(StrEnum):
    """How a record's incremental cost was obtained."""

    REPORTED = "reported"
    DERIVED = "derived"
    FIRST = "first"
    UNKNOWN = "unknown"
    BACKFILLED = "backfilled"
    LEGACY = "legacy"
    CUMULATIVE_SUMMED = "cumulative_summed"


class Cost(BaseModel):
    """A call's own spend and its session's running total."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    incremental_usd: float | None = None
    cumulative_usd: float | None = None
    basis: CostBasis = CostBasis.UNKNOWN
    reported_usd: float | None = None
    legacy_usd: float | None = None

    @field_validator(
        "incremental_usd", "cumulative_usd", "reported_usd", "legacy_usd", mode="before"
    )
    @classmethod
    def _number_or_absent(cls, value: object) -> object:
        """A figure that is not a number reads as absent."""
        if isinstance(value, bool) or not isinstance(value, int | float):
            return None
        return value


class UsageRecord(BaseModel):
    """A line of the ledger. Every field after `unit`/`node`/`at` has a default,
    so a line written before a field existed loads; `extra="ignore"` lets a line
    a later version wrote, with fields this one does not know, load too."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    kind: str = "agent"
    at: str
    unit: str
    node: str
    round: int = 0
    change: str = ""
    repo: str = ""
    tier: str = ""
    role: str = ""
    model: str | None = None
    runtime: str = ""
    session_id: str | None = None
    resumed: bool = False
    input_tokens: int | None = None
    output_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cost: Cost | None = None
    turns: int | None = None
    duration_ms: int | None = None
    usage_source: UsageSource = "none"
    # What the agent itself reported, kept beside the gateway's figures above
    # when both exist, so a report can show the difference.
    reported: Usage | None = None
    outcome: str = ""

    @model_validator(mode="before")
    @classmethod
    def _read_cost(cls, raw: object) -> object:
        """A line with a flat figure and no `cost` object is a legacy row: the old
        figure is kept apart and never summed as incremental. A line with the
        object is read from the object alone; a `cost` that is not an object is
        absent."""
        if not isinstance(raw, dict):
            return raw
        cost = raw.get("cost")
        if isinstance(cost, dict | Cost):
            return raw
        flat = raw.get("cost_usd")
        if cost is None and isinstance(flat, int | float) and not isinstance(flat, bool):
            return raw | {"cost": {"basis": CostBasis.LEGACY, "legacy_usd": flat}}
        return raw | {"cost": None}


def ledger_lock(path: Path) -> AbstractContextManager[None]:
    """The lock appends and the archive roll-up take, so a rewrite of the ledger
    never drops a line appended meanwhile."""
    return file_lock(path.with_name(f"{path.name}.lock"))


def append_record(path: Path, record: BaseModel) -> None:
    """Add `record` as a line of the ledger. Raises `OSError` when it cannot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with ledger_lock(path), path.open("a") as ledger:
        ledger.write(record.model_dump_json() + "\n")


def forget_told() -> None:
    """Let a failure already reported be reported again (a new process, a test)."""
    with _told_lock:
        _told.clear()


def record_call(record: UsageRecord, say: Callable[[str], None]) -> None:
    """Add `record` to the active installation's ledger, never raising, and
    export its figures as metrics when telemetry is on."""
    record_line(record, say)
    export_call(record)


def export_call(record: UsageRecord) -> None:
    """Add an agent record's cost and tokens to the metrics, by bounded
    attributes only: never a unit, change or session. A figure the record does
    not have adds nothing; measured and estimated figures are separate series."""
    source = "estimated" if record.usage_source == "estimated" else "measured"
    attributes = {
        "repo": record.repo,
        "tier": record.tier,
        "node": record.node,
        "role": record.role,
        "model": record.model or "default",
        "source": source,
    }
    if record.usage_source == "none":
        return
    if record.cost is not None and record.cost.incremental_usd is not None:
        telemetry.count("abk.agent.cost", record.cost.incremental_usd, **attributes)
    for kind, tokens in (
        ("input", record.input_tokens),
        ("output", record.output_tokens),
        ("cache_read", record.cache_read_input_tokens),
        ("cache_creation", record.cache_creation_input_tokens),
    ):
        if tokens is not None:
            telemetry.count("abk.agent.tokens", tokens, **attributes, kind=kind)


def record_line(record: BaseModel, say: Callable[[str], None]) -> None:
    """Add any line (an agent call, a span) to the ledger, never raising.

    A record that cannot be kept — no workspace is loaded, or the write
    fails — is dropped, and `say` is told once per process for each distinct
    reason.
    """
    root = config.active_root()
    if root is None:
        problem = "no workspace is loaded"
    else:
        try:
            path = Installation(config.active(), root).state_dir / LEDGER_NAME
            append_record(path, record)
            return
        except Exception as error:  # noqa: BLE001 — a ledger is never a run's to lose
            problem = f"the ledger could not be written: {error}"
    with _told_lock:
        if problem in _told:
            return
        _told.add(problem)
    say(f"the usage ledger is not recording ({problem})")


_FIGURES = (
    "input_tokens",
    "output_tokens",
    "cache_read_input_tokens",
    "cache_creation_input_tokens",
    "turns",
    "duration_ms",
)


def combine_records(parts: list[UsageRecord]) -> UsageRecord:
    """The last part, carrying each figure summed over the parts that report it."""
    if len(parts) == 1:
        return parts[0]
    summed: dict[str, float | int | None] = {}
    for name in _FIGURES:
        reported = [v for p in parts if (v := getattr(p, name)) is not None]
        summed[name] = sum(reported) if reported else None
    reported = [p.reported for p in parts if p.reported is not None]
    return parts[-1].model_copy(
        update=summed
        | {
            "reported": _combine_usage(reported) if reported else None,
            "cost": _combine_cost([p.cost for p in parts]),
        }
    )


def _combine_cost(parts: list[Cost | None]) -> Cost | None:
    """The last part's cost with the incremental and reported figures summed over the parts."""
    present = [p for p in parts if p is not None]
    if not present:
        return None
    summed: dict[str, float | None] = {}
    for name in ("incremental_usd", "reported_usd", "legacy_usd"):
        figures = [v for p in present if (v := getattr(p, name)) is not None]
        summed[name] = sum(figures) if figures else None
    return present[-1].model_copy(update=summed)


def _combine_usage(parts: list[Usage]) -> Usage:
    """Each token count summed over the parts that report it."""
    summed: dict[str, int | None] = {}
    for name in Usage.model_fields:
        counts = [v for p in parts if (v := getattr(p, name)) is not None]
        summed[name] = sum(counts) if counts else None
    return Usage(**summed)


def read_lines(path: Path) -> list[str]:
    """The ledger's lines; none when there is no ledger. A line cut off inside a
    multibyte character decodes with a replacement character, so it fails to
    parse and is skipped like any half-written line instead of failing the read."""
    try:
        return path.read_text(errors="replace").splitlines()
    except FileNotFoundError:
        return []


def read_ledger(path: Path) -> list[UsageRecord]:
    """The ledger's agent records; see `records_in`."""
    return records_in(read_lines(path))


def records_in(lines: list[str]) -> list[UsageRecord]:
    """The ledger's records, one per unit, node and round; see `grouped_records`."""
    return [combine_records(parts) for parts in grouped_records(lines)]


def grouped_records(lines: list[str]) -> list[list[UsageRecord]]:
    """The ledger's lines grouped by call, each group the lines `records_in` combines into one
    record, so what is counted per line (a legacy row, a call of unknown cost) can be.

    The session id is an attribute of a record, not part of its key: a call
    that continues a session another node started is its own node's spend, and
    one session id may appear under several nodes. A resumed call reports the
    figures of that call alone, not a running total, so a record with `resumed`
    set adds to the record of the same node and round (a call cut off by a
    usage limit and resumed reports both). A record that is not resumed is a
    re-run of the same call and replaces what came before it. Calls with no
    session id cannot be told apart from a re-run, so each stays a record of
    its own. A line that is not
    a record (half written) is skipped."""
    calls: dict[tuple[str, str, int, str], list[UsageRecord]] = {}
    for line in lines:
        try:
            raw = json.loads(line)
            if raw.get("kind", "agent") != "agent":
                continue
            record = UsageRecord.model_validate(raw)
        except (ValueError, AttributeError, ValidationError):
            continue
        unnamed = "" if record.session_id else record.at
        key = (record.unit, record.node, record.round, unnamed)
        if record.resumed and key in calls:
            calls[key].append(record)
        else:
            calls[key] = [record]
    return list(calls.values())


def session_cumulative(session_id: str) -> float | None:
    """The cumulative figure of the last record of the session in the active ledger."""
    return _last_in_session(session_id, lambda c: c.cumulative_usd)


def session_spend(session_id: str) -> float | None:
    """The sum of the incremental figures of the session's records in the active ledger."""
    root = config.active_root()
    if root is None:
        return None
    path = Installation(config.active(), root).state_dir / LEDGER_NAME
    figures = [
        r.cost.incremental_usd
        for r in _session_records(path, session_id)
        if r.cost is not None and r.cost.incremental_usd is not None
    ]
    return sum(figures) if figures else None


def _last_in_session(session_id: str, pick: Callable[[Cost], float | None]) -> float | None:
    root = config.active_root()
    if root is None:
        return None
    path = Installation(config.active(), root).state_dir / LEDGER_NAME
    for record in reversed(_session_records(path, session_id)):
        # A gateway record's cumulative figure is the gateway's running sum, not the runtime's
        # total, so it is no baseline for deriving what the runtime spent.
        if record.usage_source == "gateway":
            continue
        if record.cost is not None and (figure := pick(record.cost)) is not None:
            return figure
    return None


def _session_records(path: Path, session_id: str) -> list[UsageRecord]:
    """Every agent line of the session, in the order written, uncombined."""
    found = []
    try:
        lines = read_lines(path)
    except OSError:
        return []
    for line in lines:
        try:
            raw = json.loads(line)
            if raw.get("kind", "agent") != "agent" or raw.get("session_id") != session_id:
                continue
            found.append(UsageRecord.model_validate(raw))
        except (ValueError, AttributeError, ValidationError):
            continue
    return found
