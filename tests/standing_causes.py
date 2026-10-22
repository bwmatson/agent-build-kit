"""The two kinds of cause as the spec names them, for tests that run over each."""

from __future__ import annotations

from collections.abc import Sequence

from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import Unit

__all__ = ["EVENT", "REPLANS", "STANDING", "replan"]

# What a replan does to a unit's record: it plans the same graph again, or leaves the unit out
# (demotion) and then plans it again (promotion).
REPLANS = ("a replan", "a demotion and a promotion")

STANDING = [
    Cause.SPLIT_HELD,
    Cause.MANUAL_STEP,
    Cause.TOO_BIG_FOR_TIER,
    Cause.GATED,
    Cause.UPSTREAM_WENT_BACK,
    Cause.BASE_CHANGED,
    Cause.RESTACK_DEFERRED,
    Cause.RESTACK_CONFLICT,
    Cause.RESTACK_HANDED_BACK,
    Cause.HOST_UNAVAILABLE,
    Cause.NETWORK_UNAVAILABLE,
    Cause.SERVICE_UNAVAILABLE,
    Cause.ENVIRONMENT,
    Cause.REWORK,
    Cause.USAGE,
    Cause.DIRTY_WORKTREE,
    Cause.ATTACHED,
    Cause.NEEDS_HUMAN,
    Cause.REVIEWER_HOLD,
    Cause.TOOLCHAIN,
    Cause.DEPTH,
    Cause.REVIEW_ESCALATED_CLASS,
    Cause.REVIEW_ESCALATED_DISAGREEMENT,
]
EVENT = [
    Cause.REQUEUED,
    Cause.RELEASED,
    Cause.ADOPTED,
    Cause.MERGED,
    Cause.AUTO_LANDED,
    Cause.CLOSED,
    Cause.RETIRED,
    Cause.FAILED,
]


def replan(store: UnitStore, how: str, units: Sequence[Unit], *, change: str) -> None:
    """Replan `change` into `store` as `how` (one of `REPLANS`) says."""
    if how == REPLANS[1]:
        store.upsert([], change=change)
    store.upsert(units, change=change)
