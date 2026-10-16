"""A provider's month as the gate judges it: a 31-day window, readings and gates built to order."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from agent_build_kit.config import GateConfig, ProviderLimitsConfig
from agent_build_kit.runtimes.providers import ProviderReading
from tests.provider_summaries import END, START
from tests.split_gate_config import gate_of, with_gate

# The ramp covers the last quarter of the window: 7.75 of its 31 days.
RAMP_SPAN = (END - START) * 0.25


def limits(pause: int = 70, ceiling: int | None = 90, buffer: int = 5) -> ProviderLimitsConfig:
    return ProviderLimitsConfig(
        usage_pause_pct=pause,
        usage_pause_ceiling_pct=ceiling,
        usage_relief_fraction=0.25,
        usage_resume_buffer_pct=buffer,
    )


def reading(used_pct: int) -> ProviderReading:
    """A good reading of the month of October 2026 at `used_pct` percent of a 200 USD budget."""
    return ProviderReading(
        used_amount=Decimal(used_pct) * 2,
        used_pct=used_pct,
        window_start=START,
        window_end=END,
    )


def before_end(span: timedelta) -> datetime:
    """The moment `span` before the window's end."""
    return END - span


def gate(*, budget: float = 200, **settings: object) -> GateConfig:
    """The `acp` split's gate on the `modal` provider with a `budget` in USD, `settings` applied
    to the gate itself (`usage_cache_minutes`, `on_unknown`, ...)."""
    return gate_of(
        with_gate({"provider": {"name": "modal", "budget_usd": budget}, **settings}),
    )
