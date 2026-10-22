"""What the split plan checks share: a held unit of groups 1 to 5 that depends on `c/0`, its split
request, and pieces in the raw shape a model sends."""

from __future__ import annotations

import json

from agent_build_kit.pipeline.planner import Plan, plan_round
from agent_build_kit.pipeline.verdict import ReviewTier, SplitRequest
from agent_build_kit.pipeline.work_graph import TaskGroup
from tests.calibration_support import limits
from tests.factories import stored_unit
from tests.tier_ceiling_support import configure

TASKS = "".join(
    f"## {n}. [app] [unit-test] Group {n}\n\n- [ ] {n}.1 Test: it.\n\n" for n in range(1, 6)
)
ALL = [
    TaskGroup(number=n, repo="app", tier="unit-test", title=f"G{n}", line=3 + 6 * n, task_count=1)
    for n in range(1, 6)
]
HELD = stored_unit("c/1", change="c", groups=(1, 2, 3, 4, 5), depends_on=("c/0",))
PIECES = tuple(f"{HELD.id}-s{k}" for k in (1, 2, 3))


def use_per_tier_sizing() -> None:
    """Per-tier ceilings in effect: 5000 for `auto` and 750 for `full`."""
    limits()
    configure(enabled=True)


def piece(
    label: str, groups: list[int], tier: str, lines: int, after: tuple[str, ...] = ()
) -> dict:
    return {
        "id": label,
        "change": "c",
        "title": f"Piece {label}",
        "repo": "app",
        "tier": "unit-test",
        "depends_on": list(after),
        "estimated_lines": lines,
        "groups": groups,
        "review_tier": tier,
    }


def split_plan(
    *pieces: dict, drivers: tuple[int, ...] = (3,), known: set[str] | None = None
) -> Plan:
    """Plan the split of `HELD` for a reply made of `pieces`; the other groups are as built."""
    request = SplitRequest(
        earned=ReviewTier.FULL, planned=ReviewTier.AUTO, lines=900, ceiling=750, drivers=drivers
    )
    return plan_round(
        changes={"c": TASKS},
        in_flight=[],
        groups=ALL,
        known=known or {"c/0"},
        split=request,
        held=HELD,
        run_claude=lambda _: json.dumps({"units": list(pieces)}),
    )


def correct() -> tuple[dict, ...]:
    """Groups 1 and 2, the driver 3 and groups 4 and 5, chained at the planned, earned and planned
    tiers."""
    first, second, third = PIECES
    return (
        piece(first, [1, 2], "auto", 300, after=("c/0",)),
        piece(second, [3], "full", 300, after=(first,)),
        piece(third, [4, 5], "auto", 300, after=(second,)),
    )
