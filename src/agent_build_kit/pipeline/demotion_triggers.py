"""The triggers that demote a review class: a revert of an auto-landed unit, and agreement below
the minimum over the most recent samples."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path

from agent_build_kit.config import ReviewConfig
from agent_build_kit.pipeline.unit_store import StoredUnit


def evaluate_demotions(
    units: Iterable[StoredUnit],
    *,
    verdicts: Path,
    audits: Path,
    demotions: Path,
    review: ReviewConfig,
    at: datetime,
    log: Callable[[str], None],
) -> None:
    """Demote each class with a reverted auto-landed unit, and each class listed in
    `review.auto_land.classes` whose agreement over its most recent `review.demotion.window`
    samples (ordered by the merge of their units) is below `review.demotion.min_agreement`. An
    error evaluating one class is logged and the others are still evaluated."""
    raise NotImplementedError
