"""What the tick's split step tests share: a planning repo whose change `feature` has six groups,
a unit `feature/1` of groups 1 to 5 held for its size on a merged `base/1`, a dependent
`feature/6` of group 6, and pieces in the raw shape a model sends.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause, HeldBy, StoredSplitRequest
from agent_build_kit.pipeline.units import HELD, MERGED, Member
from tests.cli.replan_driver import Replan, enable_review, tasks_md
from tests.factories import stored_unit

HELD_ID = "feature/1"
DEPENDENT = "feature/6"
PIECES = tuple(f"{HELD_ID}-s{k}" for k in (1, 2, 3))


def scene(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    rounds: int = 2,
    used: int = 0,
    groups: tuple[int, ...] = (1, 2, 3, 4, 5),
    drivers: tuple[int, ...] = (3,),
    joined: tuple[Member, ...] = (),
    dependent: bool = True,
    unsplittable: str = "open_pr",
) -> Replan:
    """Per-tier sizing on with `rounds` split rounds, and the held unit having used `used`, with
    `groups`, the `drivers` its request names and the groups of other changes it `joined`; the unit
    `feature/6` waits on it unless `dependent` is false; `unsplittable` is `review.unsplittable`."""
    run = Replan(tmp_path, monkeypatch, feature=tasks_md(6))
    enable_review(run, split_rounds=rounds, unsplittable=unsplittable)
    run.store.import_units(
        [
            stored_unit("base/1", change="base", groups=(1,), state=MERGED),
            stored_unit(
                HELD_ID,
                change="feature",
                groups=groups,
                depends_on=("base/1",),
                split_rounds_used=used,
                joined=joined,
            ),
            *(
                [stored_unit(DEPENDENT, change="feature", groups=(6,), depends_on=(HELD_ID,))]
                if dependent
                else []
            ),
        ]
    )
    run.store.set_state(
        HELD_ID,
        HELD,
        held_by=HeldBy.SIZE,
        cause=Cause.TOO_BIG_FOR_TIER,
        branch=f"spec/{HELD_ID}",
        pr=17,
    )
    run.store.set_split_request(
        HELD_ID,
        StoredSplitRequest(earned="full", planned="auto", lines=900, ceiling=750, drivers=drivers),
    )
    return run


def piece(uid: str, groups: list[int], tier: str, lines: int, after: tuple[str, ...] = ()) -> dict:
    return {
        "id": uid,
        "change": "feature",
        "title": f"Piece {uid}",
        "repo": "app",
        "tier": "unit-test",
        "depends_on": list(after),
        "estimated_lines": lines,
        "groups": groups,
        "review_tier": tier,
    }


def correct() -> tuple[dict, ...]:
    """Groups 1 and 2, the driver 3 and groups 4 and 5, chained at the planned, earned and
    planned tiers."""
    first, second, third = PIECES
    return (
        piece(first, [1, 2], "auto", 300, after=("base/1",)),
        piece(second, [3], "full", 300, after=(first,)),
        piece(third, [4, 5], "auto", 300, after=(second,)),
    )


def reply(*pieces: dict) -> str:
    return "Here is the split.\n\n" + json.dumps({"units": list(pieces), "joins": []})
