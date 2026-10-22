"""The sweep that keeps the outcome of each merged unit current until the recheck horizon."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from datetime import datetime
from pathlib import Path

from agent_build_kit.forges.base import Forge, RepoId
from agent_build_kit.pipeline.unit_store import StoredUnit

# Days a merged unit is rechecked for a revert; its outcome is final after that.
HORIZON_DAYS = 14


def sweep_outcomes(
    units: Iterable[StoredUnit],
    *,
    verdicts: Path,
    forge_of: Callable[[str], tuple[Forge, RepoId]],
    checkouts: Mapping[str, Path],
    trunks: Mapping[str, str],
    now: datetime,
    log: Callable[[str], None],
) -> None:
    """Derive the outcome of each unit merged within `HORIZON_DAYS` of `now` and write the
    verdict records at `verdicts` once, atomically, and only when one changed. A unit whose forge
    or checkout cannot be read is logged and the others are still derived."""
    raise NotImplementedError
