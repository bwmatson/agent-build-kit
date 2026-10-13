"""The allowance of each usage window, calibrated from the readings and the ledger on disk."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal

from agent_build_kit.config import ClaudeLimitsConfig
from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.usage_calls import UsageCall
from agent_build_kit.pipeline.usage_ledger import UsageRecord

ALLOWANCES_NAME = "usage-allowances.json"

Window = Literal["session", "weekly"]


class UsagePair(Frozen):
    """Two good readings of a window and the units that spent between them."""

    at: datetime  # the earlier reading
    gain: int  # points gained between the readings
    units: int  # distinct units with an agent record in [earlier, later)


class Calibrated(Frozen):
    """What the history gave for one window, kept with the inputs behind it."""

    quantile_pct_per_unit: float | None  # None: too few pairs to calibrate
    quantile: float
    pairs_used: int
    pairs_available: int
    computed_at: datetime


def pairs(
    calls: list[UsageCall], ledger: list[UsageRecord], window: Window, *, min_gap: timedelta
) -> list[UsagePair]:
    """The usable pairs of `window`, oldest first."""
    raise NotImplementedError


def calibrated_allowances(
    calls: list[UsageCall],
    ledger: list[UsageRecord],
    *,
    limits: ClaudeLimitsConfig,
    now: datetime,
) -> dict[str, Calibrated]:
    """Each window's calibration from the record."""
    raise NotImplementedError


def allowance_for(window: Window, found: Calibrated | None, limits: ClaudeLimitsConfig) -> int:
    """The allowance in force: the calibrated figure kept between floor and ceiling, else the
    configured one, and always the configured one with calibration off."""
    raise NotImplementedError


def read_allowances(path: Path) -> dict[str, Calibrated]:
    """The kept result; empty when the file is missing, unreadable or of another shape."""
    raise NotImplementedError


def write_allowances(path: Path, found: Mapping[str, Calibrated]) -> None:
    """Keep `found` atomically."""
    raise NotImplementedError


def refresh_allowances(state_dir: Path, *, limits: ClaudeLimitsConfig, now: datetime) -> None:
    """Compute from the files in `state_dir` and keep the result, leaving it as it was when
    either file cannot be read."""
    raise NotImplementedError
