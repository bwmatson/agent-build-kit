"""Units in review are ordered by their recorded tier (spec: review-triage)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.review_order import review_order
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.factories import new_unit
from tests.verdict_fakes import write_verdicts


@pytest.fixture
def verdicts(tmp_path: Path) -> Path:
    return tmp_path / "verdicts.json"


def ids(units: list) -> list[str]:
    return [unit.id for unit in units]


def test_units_in_review_sort_full_light_none_then_auto(verdicts: Path) -> None:
    write_verdicts(
        verdicts,
        {"a/1": ReviewTier.AUTO, "b/1": ReviewTier.LIGHT, "d/1": ReviewTier.FULL},
    )
    units = [new_unit(f"{name}/1", state=IN_REVIEW) for name in "abcd"]

    assert ids(review_order(units, verdicts)) == ["d/1", "b/1", "c/1", "a/1"]


def test_arrival_order_holds_within_a_rank(verdicts: Path) -> None:
    write_verdicts(
        verdicts,
        {"a/1": ReviewTier.LIGHT, "b/1": ReviewTier.FULL, "c/1": ReviewTier.LIGHT},
    )
    units = [new_unit(f"{name}/1", state=IN_REVIEW) for name in "abc"]

    assert ids(review_order(units, verdicts)) == ["b/1", "a/1", "c/1"]


def test_units_with_no_verdict_keep_arrival_order_among_themselves(verdicts: Path) -> None:
    write_verdicts(verdicts, {"c/1": ReviewTier.FULL})
    units = [new_unit(f"{name}/1", state=IN_REVIEW) for name in "dabc"]

    assert ids(review_order(units, verdicts)) == ["c/1", "d/1", "a/1", "b/1"]


def test_units_not_in_review_keep_their_places(verdicts: Path) -> None:
    write_verdicts(verdicts, {"c/1": ReviewTier.FULL, "a/1": ReviewTier.AUTO})
    units = [
        new_unit("a/1", state=IN_REVIEW),
        new_unit("m/1", state=MERGED),
        new_unit("p/1", state=PLANNED),
        new_unit("c/1", state=IN_REVIEW),
    ]

    assert ids(review_order(units, verdicts)) == ["c/1", "m/1", "p/1", "a/1"]


def test_the_same_input_always_gives_the_same_order(verdicts: Path) -> None:
    write_verdicts(verdicts, {"a/1": ReviewTier.LIGHT, "b/1": ReviewTier.FULL})
    units = [new_unit(f"{name}/1", state=IN_REVIEW) for name in "abc"]

    first = review_order(units, verdicts)

    assert review_order(units, verdicts) == first
    assert review_order(first, verdicts) == first
