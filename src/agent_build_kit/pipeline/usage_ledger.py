"""One record per agent call, appended to `<state_dir>/usage-ledger.jsonl`.

Best-effort: a write that fails is dropped and reported once, and never
affects a run. The reader keeps the last record per unit, node, round and
session, so a re-run or a resumed session counts once.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, ValidationError

from agent_build_kit import config
from agent_build_kit.installation import Installation
from agent_build_kit.usage import UsageSource

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
        path = Installation(config.active(), root).state_dir / LEDGER_NAME
        try:
            append_record(path, record)
            return
        except Exception as error:  # noqa: BLE001 — a ledger is never a run's to lose
            problem = f"{path} could not be written: {error}"
    with _told_lock:
        if problem in _told:
            return
        _told.add(problem)
    say(f"the usage ledger is not recording ({problem})")


def read_ledger(path: Path) -> list[UsageRecord]:
    """The ledger's records, one per unit, node, round and session: the last
    one written. A line that is not a record (half written) is skipped."""
    try:
        lines = path.read_text().splitlines()
    except FileNotFoundError:
        return []
    latest: dict[tuple[str, str, int, str | None], UsageRecord] = {}
    for line in lines:
        try:
            record = UsageRecord.model_validate(json.loads(line))
        except (ValueError, ValidationError):
            continue
        latest[(record.unit, record.node, record.round, record.session_id)] = record
    return list(latest.values())
