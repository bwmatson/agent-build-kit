"""A planning root whose split carries a gate, and the provider's reading replaced at the table's
row, for the tests of the gate lines of `abk status` and the gate checks of `abk doctor`."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from modal.types import WorkspaceBillingSummary

from agent_build_kit.runtimes import providers
from tests.cli.e2e_hold_fakes import planning
from tests.gate_hold_support import Probe
from tests.provider_summaries import summary

PROVIDER = "provider:\n  name: modal\n  budget_usd: 200"


def provider_gate(limits: str = "") -> str:
    """The body of a provider gate, with `limits` (a flow mapping) when given."""
    return PROVIDER + (f"\n  limits: {limits}" if limits else "")


def command_gate(probe: Probe) -> str:
    """The body of a command gate that runs `probe`."""
    return "command: [" + ", ".join(f"'{part}'" for part in probe.argv) + "]"


def gated_planning(tmp_path: Path, gate: str, *, split: str = "acp") -> Path:
    """An `abk.yaml` declaring `split` (and `claude_code`, which has no gate) with `gate`, the
    text of the gate's body."""
    body = "".join(f"        {line}\n" for line in gate.splitlines())
    return planning(
        tmp_path,
        "tests:\n  e2e_splits:\n"
        f"    {split}:\n      marker: runtime_{split}\n      gate:\n{body}"
        "    claude_code: {marker: runtime_claude_code}\n",
    )


def this_month(cost: str) -> WorkspaceBillingSummary:
    """The library's summary for the month the clock is in, so a reading is never past its end."""
    now = datetime.now(UTC)
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    end = datetime(now.year + now.month // 12, now.month % 12 + 1, 1, tzinfo=UTC)
    return summary(start=start, end=end, metered_cost=Decimal(cost))


def month_end() -> datetime:
    return this_month("0").end


class Reads:
    """The provider's reading function: answers `cost` (or raises `error`) and counts its calls."""

    def __init__(self, cost: str = "173.04285316", error: Exception | None = None) -> None:
        self.cost = cost
        self.error = error
        self.calls = 0

    def __call__(self) -> object:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return this_month(self.cost)


def provider_reads(monkeypatch: pytest.MonkeyPatch, reads: Reads) -> Reads:
    """Make `reads` what the `modal` row of the table reads through."""
    row = providers.PROVIDERS["modal"].model_copy(update={"read": reads})
    monkeypatch.setitem(providers.PROVIDERS, "modal", row)
    return reads
