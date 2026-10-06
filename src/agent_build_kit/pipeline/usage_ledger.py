"""One record per agent call, appended to `<state_dir>/usage-ledger.jsonl`.

Best-effort: a write that fails is dropped and reported once, and never
affects a run. The reader keeps the last record per unit, node, round and
session, adding a resumed call's figures to the call it resumed; a call with
no session id stays a record of its own.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_build_kit import config
from agent_build_kit.installation import Installation
from agent_build_kit.usage import Usage, UsageSource

LEDGER_NAME = "usage-ledger.jsonl"

# What has been reported this process, so that many units failing the same way
# say it once; guarded because units run on threads.
_told: set[str] = set()
_told_lock = threading.Lock()


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
    cost_usd: float | None = None
    turns: int | None = None
    duration_ms: int | None = None
    usage_source: UsageSource = "none"
    # What the agent itself reported, kept beside the gateway's figures above
    # when both exist, so a report can show the difference.
    reported: Usage | None = None
    reported_cost_usd: float | None = None
    outcome: str = ""


def append_record(path: Path, record: UsageRecord) -> None:
    """Add `record` as a line of the ledger. Raises `OSError` when it cannot."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as ledger:
        ledger.write(record.model_dump_json() + "\n")


def forget_told() -> None:
    """Let a failure already reported be reported again (a new process, a test)."""
    with _told_lock:
        _told.clear()


def record_call(record: UsageRecord, say: Callable[[str], None]) -> None:
    """Add `record` to the active installation's ledger, never raising.

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
    "cost_usd",
    "turns",
    "duration_ms",
    "reported_cost_usd",
)


def _combine(parts: list[UsageRecord]) -> UsageRecord:
    """The last part, carrying each figure summed over the parts that report it."""
    if len(parts) == 1:
        return parts[0]
    summed: dict[str, float | int | None] = {}
    for name in _FIGURES:
        reported = [v for p in parts if (v := getattr(p, name)) is not None]
        summed[name] = sum(reported) if reported else None
    reported = [p.reported for p in parts if p.reported is not None]
    return parts[-1].model_copy(
        update=summed | {"reported": _combine_usage(reported) if reported else None}
    )


def _combine_usage(parts: list[Usage]) -> Usage:
    """Each token count summed over the parts that report it."""
    summed: dict[str, int | None] = {}
    for name in Usage.model_fields:
        counts = [v for p in parts if (v := getattr(p, name)) is not None]
        summed[name] = sum(counts) if counts else None
    return Usage(**summed)


def read_ledger(path: Path) -> list[UsageRecord]:
    """The ledger's records, one per unit, node, round and session.

    A resumed call keeps its session id and reports the figures of that call
    alone, not a running total, so a record with `resumed` set adds to the
    record of the call it resumed (a call cut off by a usage limit and resumed
    reports both). A record that is not resumed is a re-run of the same call
    and replaces what came before it. Calls with no session id cannot be told
    apart from a re-run, so each stays a record of its own. A line that is not
    a record (half written) is skipped."""
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return []
    calls: dict[tuple[str, str, int, str], list[UsageRecord]] = {}
    for line in lines:
        try:
            record = UsageRecord.model_validate(json.loads(line))
        except (ValueError, ValidationError):
            continue
        session = record.session_id or f"unnamed@{record.at}"
        key = (record.unit, record.node, record.round, session)
        if record.resumed and key in calls:
            calls[key].append(record)
        else:
            calls[key] = [record]
    return [_combine(parts) for parts in calls.values()]
