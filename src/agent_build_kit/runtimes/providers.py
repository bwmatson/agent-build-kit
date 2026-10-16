"""The providers a split's gate may name.

The one module where a provider is named; the tier 2 mechanism names none.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Sequence
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

from agent_build_kit.model import Frozen
from agent_build_kit.runtimes.base import Run

PROVIDERS = ("modal",)


def names() -> list[str]:
    return sorted(PROVIDERS)


class ProviderReading(Frozen):
    """A good reading: the amount used, as a whole percent of the budget, and its window."""

    used_amount: Decimal
    used_pct: int
    window_start: datetime
    window_end: datetime


class ProviderUnknown(Frozen):
    """No reading could be taken, and why."""

    reason: str


class GateCommandResult(Frozen):
    """What a gate command said: usable, held with a reason, or unknown with a reason."""

    state: Literal["usable", "held", "unknown"]
    reason: str = ""


def read_modal_summary() -> object:
    """The one place the provider's library is imported: the billing summary of the
    workspace the active login names."""
    raise NotImplementedError


def read_usage(
    name: str,
    *,
    budget_usd: float,
    now: datetime,
    read: Callable[[], object] | None = None,
) -> ProviderReading | ProviderUnknown:
    """The named provider's usage against `budget_usd`; `read` replaces the row's reader."""
    raise NotImplementedError


def run_gate_command(
    argv: Sequence[str],
    *,
    root: Path,
    timeout_seconds: float,
    run: Run = subprocess.run,
) -> GateCommandResult:
    """Run a gate command from `root`, without a shell, and read its exit status and first line."""
    raise NotImplementedError
