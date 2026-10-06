"""One record per agent call, appended to `<state_dir>/usage-ledger.jsonl`.

Best-effort: a write that fails is dropped and reported once, and never
affects a run. The reader keeps the last record per unit, node, round and
session, so a re-run or a resumed session counts once.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from agent_build_kit.usage import UsageSource

LEDGER_NAME = "usage-ledger.jsonl"


class UsageRecord(BaseModel):
    """A line of the ledger. Read with `extra="ignore"` so older lines load."""

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


def read_ledger(path: Path) -> list[UsageRecord]:
    """The ledger's records, one per unit, node, round and session."""
    raise NotImplementedError
