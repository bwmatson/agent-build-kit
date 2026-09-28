"""Per-unit cost accounting.

The ledger no longer decides whether work may start — the live usage endpoint
answers that directly (tests/test_usage_live.py). It stays because the run log
should be able to say what a unit cost, and because it is the only per-unit
attribution available: the endpoint reports the account, not who spent it.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.pipeline.usage_guard import UsageLedger


def test_records_and_totals_what_we_spent(tmp_path: Path) -> None:
    ledger = UsageLedger(tmp_path / "usage.jsonl")
    since = datetime.now(UTC) - timedelta(minutes=10)

    ledger.record(0.25, unit="u1")
    ledger.record(0.75, unit="u2")

    assert ledger.spend_since(since) == 1.0
    assert ledger.runs_since(since) == 2


def test_spend_can_be_totalled_from_a_point_in_time(tmp_path: Path) -> None:
    """Run logs ask "what did this run cost", not "what has ever been spent"."""
    ledger = UsageLedger(tmp_path / "usage.jsonl")
    old = datetime.now(UTC) - timedelta(hours=3)

    ledger.record(5.0, unit="old", at=old)
    ledger.record(0.5, unit="new")

    assert ledger.spend_since(datetime.now(UTC) - timedelta(minutes=30)) == 0.5


def test_the_ledger_survives_a_restart(tmp_path: Path) -> None:
    """The runner is a scheduled job, not a daemon: each tick is a new process,
    so an in-memory total would reset to zero on every run."""
    path = tmp_path / "usage.jsonl"
    UsageLedger(path).record(0.4, unit="u1")

    assert UsageLedger(path).spend_since(datetime.now(UTC) - timedelta(minutes=5)) == 0.4


def test_a_corrupt_line_does_not_lose_the_rest(tmp_path: Path) -> None:
    """A half-written line from a killed process shouldn't take the ledger with
    it — but it also shouldn't be silently treated as zero spend."""
    path = tmp_path / "usage.jsonl"
    ledger = UsageLedger(path)
    ledger.record(0.4, unit="u1")
    with path.open("a") as f:
        f.write("{not json\n")
    ledger.record(0.6, unit="u2")

    assert UsageLedger(path).spend_since(datetime.now(UTC) - timedelta(minutes=5)) == 1.0


def test_recorded_runs_carry_what_they_were_for(tmp_path: Path) -> None:
    """The run log has to be able to answer "what consumed the window"."""
    path = tmp_path / "usage.jsonl"
    UsageLedger(path).record(0.4, unit="add-marker/1")

    entry = json.loads(path.read_text().splitlines()[0])

    assert entry["unit"] == "add-marker/1"
    assert entry["cost_usd"] == 0.4
    assert "at" in entry
