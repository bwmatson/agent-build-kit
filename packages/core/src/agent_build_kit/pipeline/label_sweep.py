"""Taking the stale state label off the pull requests of units that finished.

A step of every round: each finished unit's pull request is cleared once and
recorded in a machine-local file, a bounded few a round. The record is only an
optimisation, so losing it costs one more pass that finds the pull requests
clean.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Sequence
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


def capped_by_repo(
    pairs: Iterable[tuple[str, int]], repo_order: Sequence[str], limit: int
) -> tuple[list[tuple[str, int]], int]:
    """Up to `limit` of the (repo, pull request) pairs, repos in `repo_order` and lowest number
    first within each, and how many more there are. A pair of a repo not in `repo_order` is left
    out. The one selection every capped post-poll sweep makes."""
    wanted = set(pairs)
    ordered = [
        (repo, pr) for repo in repo_order for pr in sorted(n for r, n in wanted if r == repo)
    ]
    return ordered[:limit], max(len(ordered) - limit, 0)


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
    chosen, remaining = capped_by_repo(
        {
            (unit.repo, unit.pr)
            for unit in units
            if unit.pr is not None
            and unit.state in FINISHED
            and unit.pr not in done.get(unit.repo, [])
        },
        repo_order,
        limit,
    )
    for repo, pr in chosen:
        if labels.clear_state(repo, pr) is not ClearOutcome.FAILED:
            _record(path, repo, pr)
    if remaining:
        log(f"label sweep: {remaining} remain")
