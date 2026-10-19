"""The outcome a verdict record gains: derived from a unit's history and its repository."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

from agent_build_kit.forges.base import Forge, RepoId
from agent_build_kit.pipeline.unit_store import StoredUnit


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
    raise NotImplementedError
