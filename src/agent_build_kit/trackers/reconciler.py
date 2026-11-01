"""Pushes the wanted board to a repo's tracker, making only the calls that differ.

Spec: tracker-push."""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from pathlib import Path

from agent_build_kit.model import Frozen
from agent_build_kit.pipeline.units import Unit

ERRORS_COUNTER = "abk.tracker.errors"


class PassReport(Frozen):
    """What one pass did. `awaiting` holds the markers of items left for the inbound sync because
    the board changed them; `stopped` is set when a rate limit ended the pass."""

    created: int = 0
    updated: int = 0
    errors: int = 0
    awaiting: tuple[str, ...] = ()
    stopped: bool = False


def reconcile(
    repo: str,
    *,
    changes_dir: Path,
    changes: Sequence[str],
    units: Sequence[Unit],
    repo_url: str,
    state_dir: Path,
    tracking_dir: Path | None = None,
    archived: Collection[str] = (),
    log: Callable[[str], None] = print,
) -> PassReport:
    """One pass over `repo`'s tracker: level by level, create what has no item (looking for its
    marker first), update what differs from the recorded snapshot, and record each success before
    the next call. `state_dir` holds the machine-local snapshot. Never raises for a tracker
    failure."""
    raise NotImplementedError
