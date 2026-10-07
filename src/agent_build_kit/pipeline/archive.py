"""Archiving a change once all of its work has landed.

`openspec archive` folds a change's spec deltas into `openspec/specs/`, which
is what keeps those specs describing current behaviour rather than intentions
(docs/architecture.md). It is the only step that rewrites the
planning repo's own record, so three rules apply:

- **Only when every unit has merged.** Archiving earlier publishes behaviour
  that isn't in `main`.
- **In merge order.** Two changes touching the same requirement conflict when
  the second is archived, and the later one has to apply on top of the
  earlier.
- **Never twice.** "All merged" stays true forever, so without a check every
  round would try again and fail noisily.

A failure here is contained, not swallowed. An archive conflict means two
changes disagree about a requirement, which a person should look at rather
than a pipeline paper over — but archiving is housekeeping, so it must not end
the tick before the other changes are archived or anything is built. The
failure is logged, recorded with a fingerprint of what the archive depended on
(`failed_archives`, shown by `abk status`), and not retried until the change's
files or one of its units' states change.
"""

from __future__ import annotations

import hashlib
import json
import logging
import subprocess
from collections.abc import Callable
from pathlib import Path

from agent_build_kit import openspec
from agent_build_kit.pipeline.run_log import remove_change_logs
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import SATISFIED, satisfied_landed
from agent_build_kit.pipeline.usage_report import roll_up_change

logger = logging.getLogger(__name__)

FAILED_FILE = "archive-failed.json"

# A subprocess.run-like callable, for tests to record the OpenSpec CLI call
# instead of making it.
Runner = Callable[..., subprocess.CompletedProcess]

# A state that means a unit will never merge, and so must not hold its change
# back: "unplanned" is work the plan dropped, which would otherwise strand the
# change permanently.
FINISHED_WITHOUT_MERGING = ("unplanned",)


def is_ready_to_archive(change: str, units: list[StoredUnit]) -> bool:
    """Has every unit of this change landed?

    A satisfied unit never opens a PR of its own to merge, so it counts once
    the work it was built on has (`satisfied_landed`) — not before: it may sit
    on another change's branch that is still in review, and archiving then
    would publish behaviour that is not in `main`.
    """
    mine = [unit for unit in units if unit.carries(change)]
    if not mine:
        # Nothing merged is not the same as everything merged; an empty change
        # would otherwise archive itself the moment it appeared.
        return False

    return all(
        unit.state == "merged"
        or unit.state in FINISHED_WITHOUT_MERGING
        or (unit.state == SATISFIED and satisfied_landed(unit, units))
        for unit in mine
    )


def _merged_at(change: str, units: list[StoredUnit]) -> str:
    """When this change's last unit merged, for ordering."""
    stamps = [
        entry.get("at", "")
        for unit in units
        if unit.carries(change)
        for entry in unit.history
        if entry.get("state") == "merged"
    ]
    return max(stamps) if stamps else ""


def _already_archived(change: str, planning_repo: Path, specs_dir: str = "openspec") -> bool:
    archive = planning_repo / specs_dir / "changes" / "archive"
    if not archive.exists():
        return False
    return any(entry.name.endswith(f"-{change}") for entry in archive.iterdir())


def _fingerprint(change: str, units: list[StoredUnit], directory: Path) -> str:
    """What a failed archive depended on: every file of the change (a conflict is
    fixed by editing its delta specs as much as its tasks) and its units' states."""
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.rglob("*") if p.is_file()):
        try:
            content = path.read_bytes()
        except OSError:
            content = b""
        digest.update(path.relative_to(directory).as_posix().encode() + b"\0" + content + b"\0")
    states = sorted(f"{unit.id}={unit.state}" for unit in units if unit.carries(change))
    digest.update("\n".join(states).encode())
    return digest.hexdigest()


def _load_failed(state_dir: Path | None) -> dict[str, dict[str, str]]:
    if state_dir is None:
        return {}
    try:
        recorded = json.loads((state_dir / FAILED_FILE).read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(recorded, dict) or not all(isinstance(e, dict) for e in recorded.values()):
        return {}
    return recorded


def failed_archives(state_dir: Path) -> dict[str, str]:
    """The changes whose archive failed and has not been retried, with why."""
    return {change: str(e.get("reason", "")) for change, e in _load_failed(state_dir).items()}


def archive_ready_changes(
    units: list[StoredUnit],
    *,
    planning_repo: Path,
    run: Runner | None = None,
    may_archive: Callable[[str], bool] = lambda change: True,
    specs_dir: str = "openspec",
    run_logs: Path | None = None,
    usage_ledger: Path | None = None,
    state_dir: Path | None = None,
) -> list[str]:
    """Archive every change whose units have all merged, oldest merge first —
    and that `may_archive` lets through: the tick passes whether the change
    has been deployed and passed its live tests (verify.py).

    A change that fails to archive, or has no directory (withdrawn), is logged
    and skipped; `state_dir` records the failure so it is not retried until its
    fingerprint changes.

    Returns the changes archived, so the caller can commit them and say so in
    the run log.
    """
    candidates = {member.change for unit in units for member in unit.members()}
    ready = {
        change
        for change in candidates
        if is_ready_to_archive(change, units)
        and not _already_archived(change, planning_repo, specs_dir)
        and may_archive(change)
    }

    before = _load_failed(state_dir)
    # A record outlives only a change still waiting to archive: one archived by
    # hand, or no longer finished, would otherwise show as failed forever.
    failed = {
        change: entry
        for change, entry in before.items()
        if is_ready_to_archive(change, units)
        and not _already_archived(change, planning_repo, specs_dir)
    }
    archived: list[str] = []
    for change in sorted(ready, key=lambda name: _merged_at(name, units)):
        directory = planning_repo / specs_dir / "changes" / change
        if not directory.is_dir():
            reason = "withdrawn: no change directory"
            if failed.get(change, {}).get("reason") != reason:
                logger.info("not archiving %s: %s", change, reason)
                failed[change] = {"fingerprint": "withdrawn", "reason": reason}
            continue
        fingerprint = _fingerprint(change, units, directory)
        if failed.get(change, {}).get("fingerprint") == fingerprint:
            continue
        try:
            # A conflict is not auto-resolved: it is recorded for a person.
            openspec.archive(change, cwd=planning_repo, run=run)
        except RuntimeError as exc:
            detail = [line for line in str(exc).splitlines()[1:] if line.strip()]
            reason = detail[0] if detail else str(exc)
            logger.warning("archiving %s failed, skipping it: %s", change, str(exc))
            failed[change] = {"fingerprint": fingerprint, "reason": reason}
            continue
        failed.pop(change, None)
        archived.append(change)
        if usage_ledger is not None:
            try:
                roll_up_change(usage_ledger, change)
            except OSError:
                # The ledger is a record, never a reason to stop archiving; the
                # detail stays and is rolled up by nothing, but still reports.
                pass
        if run_logs is not None:
            remove_change_logs(run_logs, change)

    if state_dir is not None and failed != before:
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / FAILED_FILE).write_text(json.dumps(failed, indent=2, sort_keys=True))
    return archived
