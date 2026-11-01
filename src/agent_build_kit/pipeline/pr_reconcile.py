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
from agent_build_kit.pipeline.pr_poller import PrState, state_path
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import CLOSED, FAILED, HELD, IN_REVIEW, MERGED, RUNNING

# The states whose unit has not recorded how its pull request ended.
RECONCILED = (RUNNING, IN_REVIEW, FAILED, HELD)


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
    caches: dict[str, dict] = {}
    corrections: list[Correction] = []
    for unit in store.all():
        if unit.pr is None or unit.state not in RECONCILED or (only and unit.id != only):
            continue
        if unit.repo not in caches:
            caches[unit.repo] = PrState.load(state_path(state_dir, unit.repo))
        shown = (caches[unit.repo].get(str(unit.pr)) or {}).get("state")
        if shown not in (MERGED, CLOSED):
            continue
        event = "merged" if shown == MERGED else "closed"
        if not dry_run and not dispatch(event, unit.pr, repo=unit.repo):
            continue
        corrections.append(Correction(unit=unit.id, pr=unit.pr, event=event))
        log(f"reconciled: {unit.id} #{unit.pr} {event} on the forge")
    return corrections
