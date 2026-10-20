"""The outcome a verdict record gains: derived from a unit's history and its repository."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

from agent_build_kit.forges.base import Forge, RepoId
from agent_build_kit.pipeline.review_revert import reverts_merge
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit
from agent_build_kit.pipeline.units import UnitState


class Outcome(StrEnum):
    OPEN = "open"
    CLEAN = "clean"
    REWORKED = "reworked"
    REVERTED = "reverted"
    CLOSED = "closed"


def with_outcome(
    records: Mapping[str, Mapping[str, Any]],
    unit: StoredUnit,
    *,
    forge: Forge,
    repo: RepoId,
    checkout: Path,
    trunk: str,
) -> dict[str, dict[str, Any]]:
    """`records` (verdict records by unit id) with the unit's record holding `outcome`, `reworks`
    (the count of history entries whose cause is `rework`) and `revert_checked` (false when the
    forge could not say which commit the merge produced). A unit with no record is left alone."""
    if unit.id not in records:
        return {uid: dict(record) for uid, record in records.items()}
    reworks = sum(1 for entry in unit.history if entry.get("cause") == Cause.REWORK)
    checked = False
    if unit.state is UnitState.CLOSED:
        outcome = Outcome.CLOSED
    elif unit.state is not UnitState.MERGED:
        outcome = Outcome.OPEN
    else:
        merge = forge.merge_commit(repo, unit.pr) if unit.pr is not None else None
        checked = merge is not None
        if merge and reverts_merge(
            checkout, trunk=trunk, merge_commit=merge, repo=repo, pr=unit.pr or 0
        ):
            outcome = Outcome.REVERTED
        else:
            outcome = Outcome.REWORKED if reworks else Outcome.CLEAN
    derived = {"outcome": outcome.value, "reworks": reworks, "revert_checked": checked}
    return {
        uid: {**record, **derived} if uid == unit.id else dict(record)
        for uid, record in records.items()
    }
