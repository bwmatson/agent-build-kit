"""Reads the changes people made on a repo's board since the last poll (spec: tracker-pull).

Modelled on the pull request poller: a cursor kept in the repo's machine-local snapshot, a first
poll that only records, and a backoff after repeated failures. A change whose revision the kit
recorded for the item when it wrote it is the kit's own and is not reported."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import datetime
from pathlib import Path

from agent_build_kit import trackers
from agent_build_kit.pipeline import spans
from agent_build_kit.pipeline.pr_poller import BACKOFF, FAILURES_BEFORE_BACKOFF
from agent_build_kit.trackers.base import Change, Cursor
from agent_build_kit.trackers.config import TrackerConfigError, section_for
from agent_build_kit.trackers.reconciler import (
    SNAPSHOT_WRITTEN,
    read_snapshot,
    snapshot_path,
    update_snapshot,
)

CURSOR_KEY = "poll_cursor"
FAILURES_KEY = "poll_failures"
QUIET_UNTIL_KEY = "poll_quiet_until"
PULLED_KEY = "pulled_at"


def _own_revisions(kept: Mapping[str, object]) -> dict[str, set[str]]:
    """Every revision the kit wrote for each item id since the poll last passed."""
    written = kept.get(SNAPSHOT_WRITTEN)
    if not isinstance(written, dict):
        return {}
    return {
        str(item_id): {str(revision) for revision in revisions}
        for item_id, revisions in written.items()
        if isinstance(revisions, list)
    }


def _failure_count(current: Mapping[str, object]) -> int:
    try:
        return int(str(current.get(FAILURES_KEY, 0)))
    except ValueError:
        return 0


def _quiet(kept: Mapping[str, object]) -> bool:
    try:
        until = datetime.fromisoformat(str(kept.get(QUIET_UNTIL_KEY)))
    except ValueError:
        return False
    return spans.clock.now() < until


def poll_board(
    repo: str, *, state_dir: Path, log: Callable[[str], None] = print
) -> tuple[Change, ...]:
    """The changes to `repo`'s board that the kit did not write and has not reported before.

    Records the cursor in the repo's machine-local snapshot. The first poll with no cursor only
    records; a failed poll is logged and, after two in a row, backs the next ones off."""
    try:
        if section_for(repo) is None:
            return ()
        tracker = trackers.for_repo(repo)
    except TrackerConfigError as error:
        log(f"tracker {repo}: poll skipped: {error}")
        return ()
    if tracker is None:
        return ()
    path = snapshot_path(state_dir, repo)
    kept = read_snapshot(path)
    if _quiet(kept):
        return ()
    stored = kept.get(CURSOR_KEY)
    cursor = Cursor(value=str(stored)) if stored is not None else None
    try:
        changes, moved = tracker.changed_since(cursor)
    except Exception as error:  # noqa: BLE001 — a host answers in its own errors
        log(f"tracker {repo}: poll failed: {type(error).__name__}: {error}")
        quiet = (spans.clock.now() + BACKOFF).isoformat()

        def failed(current: dict[str, object]) -> None:
            failures = _failure_count(current) + 1
            current[FAILURES_KEY] = failures
            if failures >= FAILURES_BEFORE_BACKOFF:
                current[QUIET_UNTIL_KEY] = quiet

        update_snapshot(path, failed)
        return ()

    own = _own_revisions(kept)
    pulled = spans.clock.now().isoformat()

    def advance(current: dict[str, object]) -> None:
        current[CURSOR_KEY] = moved.value
        current[PULLED_KEY] = pulled
        # Forget the revisions this poll has passed; a write made since is kept for the next.
        remaining = {
            item_id: sorted(left)
            for item_id, revisions in _own_revisions(current).items()
            if (left := revisions - own.get(item_id, set()))
        }
        current[SNAPSHOT_WRITTEN] = remaining
        current.pop(FAILURES_KEY, None)
        current.pop(QUIET_UNTIL_KEY, None)

    update_snapshot(path, advance)
    if cursor is None:
        return ()
    return tuple(
        change for change in changes if change.revision not in own.get(change.item_id, set())
    )
