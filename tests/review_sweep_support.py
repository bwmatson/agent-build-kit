"""Merged units, a landed pull request and a run of the outcome sweep, for the tests of it."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_build_kit.forges.base import Forge, RepoId
from agent_build_kit.pipeline.review_outcome_sweep import sweep_outcomes
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState
from tests.factories import commit, stored_unit
from tests.forges.stand_in import StandInForge

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
REPO = RepoId(forge="stand_in", account="example", name="app")


def merged(uid: str, pr: int, age: timedelta, *, repo: str = "app") -> StoredUnit:
    history = (
        {"state": "running", "at": (NOW - age - timedelta(days=1)).isoformat()},
        {"state": "merged", "at": (NOW - age).isoformat(), "cause": "merged"},
    )
    return stored_unit(uid, state=UnitState.MERGED, pr=pr, repo=repo, history=history)


def land(forge: StandInForge, app: Path, pr: int) -> str:
    sha = commit(app, f"change-{pr}.txt")
    forge.merged[pr] = sha
    return sha


def sweep(
    units: list[StoredUnit],
    verdicts: Path,
    forge: Forge,
    app: Path,
    *,
    log: list[str] | None = None,
    forge_of: Callable[[str], tuple[Forge, RepoId]] | None = None,
) -> None:
    sweep_outcomes(
        units,
        verdicts=verdicts,
        forge_of=forge_of or (lambda name: (forge, REPO)),
        checkouts={"app": app, "platform": app},
        trunks={"app": "main", "platform": "main"},
        now=NOW,
        log=(log if log is not None else []).append,
    )
