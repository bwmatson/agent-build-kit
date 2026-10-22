"""The order units in review are shown in: the highest recorded review tier first."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from agent_build_kit.pipeline.unit_store import StoredUnit


def review_order(units: Sequence[StoredUnit], verdicts: Path) -> list[StoredUnit]:
    """`units` with the places of those in review refilled by them in rank order.

    The rank is the unit's recorded tier in `verdicts`: `full`, `light`, none, `auto`, and
    arrival order (the order in `units`) within a rank. A unit not in review keeps its place."""
    raise NotImplementedError
