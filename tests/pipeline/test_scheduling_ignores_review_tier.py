"""Ordering by tier changes what is shown, never which unit a pass works on next (spec:
review-triage)."""

from __future__ import annotations

from itertools import permutations
from pathlib import Path

import pytest

from agent_build_kit.pipeline.review_order import review_order
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.factories import new_unit, started_ids
from tests.verdict_fakes import write_verdicts

# Four units in review: three carry a verdict, one carries none.
TIERS = (ReviewTier.FULL, ReviewTier.LIGHT, ReviewTier.AUTO, None)


def graph() -> list:
    reviewed = [new_unit(f"r{n}/1", state=IN_REVIEW, pr=n) for n in range(1, 5)]
    planned = [
        new_unit("p1/1", state=PLANNED, depends_on=("r1/1",)),
        new_unit("p2/1", state=PLANNED, depends_on=("r3/1",)),
        new_unit("p3/1", state=PLANNED),
        new_unit("p4/1", state=PLANNED),
    ]
    return [*planned[:2], *reviewed, *planned[2:]]


@pytest.mark.parametrize("assigned", list(permutations(TIERS)), ids=str)
def test_the_next_unit_is_the_same_whatever_the_tiers(
    assigned: tuple[ReviewTier | None, ...], tmp_path: Path
) -> None:
    verdicts = tmp_path / "verdicts.json"
    without = started_ids(graph(), slots=3)
    write_verdicts(
        verdicts,
        {f"r{n}/1": tier for n, tier in enumerate(assigned, start=1) if tier is not None},
    )

    ordered = review_order(graph(), verdicts)

    assert started_ids(ordered, slots=3) == without
