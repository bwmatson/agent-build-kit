"""The health thresholds: which of them a report breaches, and the correction each names."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from agent_build_kit.config import HealthConfig
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.trusted_cost import TrustedChanges
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.usage_report import DaySpend


class Breach(Frozen):
    """A threshold crossed: its signal, what was observed, its limit and correction, and the
    evidence a person reads."""

    signal: str
    observed: float
    limit: float
    correction: str
    evidence: tuple[str, ...] = ()


class ThresholdReport(Frozen):
    breaches: tuple[Breach, ...] = ()
    # The windows (`latest`, `previous`) that had no costed trusted change.
    lacking: tuple[str, ...] = ()


def evaluate_thresholds(
    days: Sequence[DaySpend],
    trusted: TrustedChanges,
    units: Sequence[StoredUnit],
    health: HealthConfig,
    *,
    now: datetime,
) -> ThresholdReport:
    """Each breached threshold at `now`, and the windows that lacked a costed trusted change."""
    raise NotImplementedError
