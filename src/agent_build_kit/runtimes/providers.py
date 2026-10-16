"""The providers a split's gate may name.

The one module where a provider is named; the tier 2 mechanism names none.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from decimal import ROUND_CEILING, Decimal, InvalidOperation
from pathlib import Path
from typing import Literal

from agent_build_kit.model import Frozen
from agent_build_kit.redaction import redact_text
from agent_build_kit.runtimes.base import Run

logger = logging.getLogger(__name__)

PROVIDERS = ("modal",)

# The longest reason a gate command's first line may give.
REASON_LIMIT = 200

_MODAL_MISSING = (
    "the provider's library is not installed: install the kit with the extra `modal` "
    "in the environment the tick runs in"
)


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
    from modal import Workspace

    return Workspace.from_context().billing.summary()


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)


def _month_of(now: datetime) -> tuple[datetime, datetime]:
    now = _utc(now)
    start = datetime(now.year, now.month, 1, tzinfo=UTC)
    end = datetime(now.year + now.month // 12, now.month % 12 + 1, 1, tzinfo=UTC)
    return start, end


def _unknown(reason: str) -> ProviderUnknown:
    reason = redact_text(reason, where="provider reading")
    logger.info("provider usage unknown: %s", reason)
    return ProviderUnknown(reason=reason)


def _metered_cost(summary: object) -> Decimal | str:
    """The summary's `metered_cost`, or what was wrong with it."""
    raw = getattr(summary, "metered_cost", None)
    if raw is None:
        return "the billing summary has no metered_cost"
    try:
        cost = raw if isinstance(raw, Decimal) else Decimal(str(raw))
    except InvalidOperation:
        return f"metered_cost {raw!r} is not a decimal"
    if not cost.is_finite() or cost < 0:
        return f"metered_cost {raw!r} is not a non-negative decimal"
    return cost


def _read_modal(
    budget_usd: float, now: datetime, read: Callable[[], object]
) -> ProviderReading | ProviderUnknown:
    try:
        summary = read()
    except ImportError:
        return _unknown(_MODAL_MISSING)
    except Exception as error:  # noqa: BLE001 — any failure of the call is no reading, not a crash
        return _unknown(f"{type(error).__name__}: {error}")
    cost = _metered_cost(summary)
    if isinstance(cost, str):
        return _unknown(cost)
    start, end = getattr(summary, "start", None), getattr(summary, "end", None)
    window = (_utc(start), _utc(end)) if start and end else _month_of(now)
    used_pct = int((cost * 100 / Decimal(str(budget_usd))).to_integral_value(ROUND_CEILING))
    logger.info("provider usage: %s of %s (%d%%)", cost, budget_usd, used_pct)
    return ProviderReading(
        used_amount=cost, used_pct=used_pct, window_start=window[0], window_end=window[1]
    )


def read_usage(
    name: str,
    *,
    budget_usd: float,
    now: datetime,
    read: Callable[[], object] | None = None,
) -> ProviderReading | ProviderUnknown:
    """The named provider's usage against `budget_usd`; `read` replaces the row's reader."""
    return _read_modal(budget_usd, now, read or read_modal_summary)


def run_gate_command(
    argv: Sequence[str],
    *,
    root: Path,
    timeout_seconds: float,
    run: Run = subprocess.run,
) -> GateCommandResult:
    """Run a gate command from `root`, without a shell, and read its exit status and first line."""
    try:
        done = run(
            list(argv),
            cwd=root,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return GateCommandResult(
            state="unknown",
            reason=redact_text(f"{type(error).__name__}: {error}", where="gate command"),
        )
    if done.returncode == 0:
        return GateCommandResult(state="usable")
    lines = (done.stdout or "").splitlines()
    line = redact_text(lines[0].strip(), where="gate command")[:REASON_LIMIT] if lines else ""
    return GateCommandResult(state="held", reason=line or f"gate command exited {done.returncode}")
