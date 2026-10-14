"""Taking the stale state label off the pull requests of units that finished.

A step of every round: each finished unit's pull request is cleared once and
recorded in a machine-local file, a bounded few a round. The record is only an
optimisation, so losing it costs one more pass that finds the pull requests
clean.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from pathlib import Path

from agent_build_kit.pipeline.file_lock import atomic_write_text, file_lock
from agent_build_kit.pipeline.labels import ClearOutcome, StateLabels
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.vocabulary import FINISHED

SWEPT_NAME = "labels-swept.json"


def _read(path: Path) -> dict[str, list[int]]:
    try:
        raw = json.loads(path.read_text())
        return {str(repo): [int(pr) for pr in prs] for repo, prs in raw.items()}
    except (OSError, ValueError, AttributeError, TypeError):
        return {}


def _record(path: Path, repo: str, pr: int) -> None:
    with file_lock(path.with_name(f"{path.name}.lock")):
        swept = _read(path)
        if pr not in swept.setdefault(repo, []):
            swept[repo].append(pr)
        atomic_write_text(path, json.dumps(swept, indent=2, sort_keys=True))


def sweep_finished(
    units: list[StoredUnit],
    *,
    labels: StateLabels,
    state_dir: Path,
    limit: int,
    repo_order: Sequence[str],
    log: Callable[[str], None] = print,
) -> None:
    """Clear up to `limit` finished units' pull requests not yet recorded, lowest number first
    within each repo, repos in `repo_order`. A unit of a repo not in it is left alone."""
    path = state_dir / SWEPT_NAME
    with file_lock(path.with_name(f"{path.name}.lock")):
        done = _read(path)
    pending: list[tuple[str, int]] = []
    for repo in repo_order:
        numbers = {
            unit.pr
            for unit in units
            if unit.repo == repo
            and unit.pr is not None
            and unit.state in FINISHED
            and unit.pr not in done.get(repo, [])
        }
        pending.extend((repo, pr) for pr in sorted(numbers))
    for repo, pr in pending[:limit]:
        if labels.clear_state(repo, pr) is not ClearOutcome.FAILED:
            _record(path, repo, pr)
    if len(pending) > limit:
        log(f"label sweep: {len(pending) - limit} remain")
