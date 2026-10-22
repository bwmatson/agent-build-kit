"""The order units in review are shown in: the highest recorded review tier first."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import latest_verdict

_RANK = {ReviewTier.FULL: 0, ReviewTier.LIGHT: 1, None: 2, ReviewTier.AUTO: 3}


def review_tier(unit: StoredUnit, verdicts: Path) -> ReviewTier | None:
    """The tier recorded for the unit, or None when it has no readable verdict."""
    recorded = latest_verdict(verdicts, unit.id)
    return recorded.tier if recorded else None


def review_tiers(units: Sequence[StoredUnit], verdicts: Path) -> dict[str, ReviewTier | None]:
    """The recorded tier of each unit in review, read once, by unit id."""
    return {unit.id: review_tier(unit, verdicts) for unit in units if unit.state == IN_REVIEW}


def review_order(
    units: Sequence[StoredUnit],
    verdicts: Path,
    tiers: Mapping[str, ReviewTier | None] | None = None,
) -> list[StoredUnit]:
    """`units` with the places of those in review refilled by them in rank order.

    The rank is the unit's recorded tier in `verdicts`: `full`, `light`, none, `auto`, and
    arrival order (the order in `units`) within a rank. A unit not in review keeps its place.
    `tiers` (from `review_tiers`) saves reading the file again."""
    tiers = review_tiers(units, verdicts) if tiers is None else tiers
    reviewed = sorted(
        (unit for unit in units if unit.state == IN_REVIEW),
        key=lambda unit: _RANK[tiers[unit.id]],
    )
    refill = iter(reviewed)
    return [next(refill) if unit.state == IN_REVIEW else unit for unit in units]
