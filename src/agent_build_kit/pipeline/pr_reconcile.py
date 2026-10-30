"""Comparing a unit's recorded pull request with what the forge last said of it.

The poller reports a change of a pull request once, and `events.on_merged` defers the
report while its unit is being built, so a merge the unit never recorded would stay
unrecorded. This pass reads the poller's own cache and hands a merged or closed pull
request of a unit that has not recorded it to the poller's dispatch.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.unit_store import UnitStore


class Correction(Frozen):
    """One unit the pass corrected, or would: its pull request and the event handed on."""

    unit: str
    pr: int
    event: str  # "merged" or "closed"


def reconcile(
    *,
    store: UnitStore,
    state_dir: Path,
    dispatch: Callable[..., bool],
    only: str | None = None,
    dry_run: bool = False,
    log: Callable[[str], None] = print,
) -> list[Correction]:
    """Correct each running, in-review, failed or held unit whose cached pull request
    is merged or closed, through `dispatch` as the poller calls it; `only` limits the
    pass to one unit and `dry_run` writes nothing. A unit the dispatch defers because it
    is being built is not in the result."""
    raise NotImplementedError
