"""An acceptance or narrow unit follows the pieces of a split, not the original the split closed
(spec: acceptance-follow)."""

from __future__ import annotations

import pytest

from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    IN_REVIEW,
    MERGED,
    PLANNED,
    UnitState,
    earlier_units,
    followed_dependencies,
)
from tests.factories import stored_unit

ORIGINAL = "feature/4"
PIECES = ("feature/4-s1", "feature/4-s2")
FOLLOWER = "feature/7"


def change(
    *, second: UnitState = MERGED, flag: str = "acceptance", superseded: bool = True
) -> list[StoredUnit]:
    """Units 1 to 3 merged, a closed unit 4 (superseded by two pieces unless `superseded` is
    false), the pieces, and a follower numbered 7; the second piece is in `second`."""

    def one(uid: str, **fields) -> StoredUnit:
        return stored_unit(uid, change="feature", **fields)

    return [
        one("feature/1", state=MERGED),
        one("feature/2", state=MERGED),
        one("feature/3", state=MERGED),
        one(ORIGINAL, state=CLOSED, superseded_by=PIECES if superseded else ()),
        one(PIECES[0], state=MERGED),
        one(PIECES[1], state=second),
        one(FOLLOWER, flag=flag),
    ]


def follower(units: list[StoredUnit]) -> StoredUnit:
    return next(unit for unit in units if unit.id == FOLLOWER)


@pytest.mark.parametrize("flag", ["acceptance", "narrow"])
@pytest.mark.parametrize("second", [MERGED, IN_REVIEW, PLANNED, FAILED])
def test_the_pieces_are_followed_and_the_closed_original_is_not(
    flag: str, second: UnitState
) -> None:
    units = change(second=second, flag=flag)

    ids = [unit.id for unit in earlier_units(follower(units), units)]

    assert ORIGINAL not in ids
    assert set(PIECES) <= set(ids)
    assert {"feature/1", "feature/2", "feature/3"} <= set(ids)


@pytest.mark.parametrize("flag", ["acceptance", "narrow"])
def test_followed_dependencies_list_the_pieces_and_not_the_original(flag: str) -> None:
    units = change(flag=flag)

    followed = followed_dependencies(follower(units), units)

    assert ORIGINAL not in followed
    assert set(PIECES) <= set(followed)


def test_a_closed_unit_with_no_pieces_is_still_an_earlier_unit() -> None:
    units = [*change(), stored_unit("feature/5", change="feature", state=CLOSED)]

    ids = [unit.id for unit in earlier_units(follower(units), units)]
    followed = followed_dependencies(follower(units), units)

    assert "feature/5" in ids and "feature/5" in followed
    assert ORIGINAL not in ids and ORIGINAL not in followed
