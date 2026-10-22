"""The outcome sweep (spec: review-outcomes): merged units are rechecked until the horizon.

The repository is a temporary git one and the forge is the stand-in; the clock is passed in."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.forges.base import Forge, RepoId
from agent_build_kit.pipeline.review_outcome_sweep import HORIZON_DAYS, sweep_outcomes
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import UnitState
from tests.factories import commit, commit_files, init_repo, stored_unit
from tests.forges.stand_in import StandInForge

NOW = datetime(2026, 10, 20, 12, 0, tzinfo=UTC)
REPO = RepoId(forge="stand_in", account="example", name="app")


@pytest.fixture
def app(tmp_path: Path) -> Path:
    repo = init_repo(tmp_path / "app")
    commit(repo, "base.txt")
    return repo


@pytest.fixture
def forge() -> StandInForge:
    return StandInForge()


@pytest.fixture
def verdicts(tmp_path: Path) -> Path:
    return tmp_path / "verdicts.json"


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


def revert(app: Path, sha: str) -> None:
    commit_files(app, f"Revert\n\nThis reverts commit {sha}.", {"revert.txt": sha})


def write(path: Path, *units: str) -> None:
    path.write_text(json.dumps({uid: {"brief": True, "final": True} for uid in units}))


def read(path: Path) -> dict:
    return json.loads(path.read_text())


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


def test_every_merged_unit_inside_the_horizon_is_updated_and_none_outside_it(
    app: Path, forge: StandInForge, verdicts: Path
) -> None:
    inside = merged("c/1", 1, timedelta(days=1))
    edge = merged("c/2", 2, timedelta(days=HORIZON_DAYS - 1))
    outside = merged("c/3", 3, timedelta(days=HORIZON_DAYS + 1))
    for pr in (1, 2, 3):
        land(forge, app, pr)
    write(verdicts, "c/1", "c/2", "c/3")

    sweep([inside, edge, outside], verdicts, forge, app)

    recorded = read(verdicts)
    assert recorded["c/1"]["outcome"] == "clean"
    assert recorded["c/2"]["outcome"] == "clean"
    assert "outcome" not in recorded["c/3"]


def test_a_revert_after_the_horizon_changes_nothing(
    app: Path, forge: StandInForge, verdicts: Path
) -> None:
    old = merged("c/1", 1, timedelta(days=HORIZON_DAYS + 1))
    sha = land(forge, app, 1)
    verdicts.write_text(json.dumps({"c/1": {"brief": True, "final": True, "outcome": "clean"}}))
    revert(app, sha)

    sweep([old], verdicts, forge, app)

    assert read(verdicts)["c/1"]["outcome"] == "clean"


def test_a_revert_inside_the_horizon_is_found(
    app: Path, forge: StandInForge, verdicts: Path
) -> None:
    recent = merged("c/1", 1, timedelta(days=2))
    sha = land(forge, app, 1)
    write(verdicts, "c/1")
    revert(app, sha)

    sweep([recent], verdicts, forge, app)

    assert read(verdicts)["c/1"]["outcome"] == "reverted"


def test_a_second_sweep_with_nothing_new_writes_nothing(
    app: Path, forge: StandInForge, verdicts: Path
) -> None:
    unit = merged("c/1", 1, timedelta(days=1))
    land(forge, app, 1)
    write(verdicts, "c/1")
    sweep([unit], verdicts, forge, app)
    before = (verdicts.stat().st_ino, verdicts.stat().st_mtime_ns, verdicts.read_bytes())

    sweep([unit], verdicts, forge, app)

    assert (verdicts.stat().st_ino, verdicts.stat().st_mtime_ns, verdicts.read_bytes()) == before


def test_an_error_reading_one_unit_is_logged_and_the_others_are_still_derived(
    app: Path, forge: StandInForge, verdicts: Path
) -> None:
    broken = merged("c/1", 1, timedelta(days=1), repo="platform")
    fine = merged("c/2", 2, timedelta(days=1))
    land(forge, app, 2)
    write(verdicts, "c/1", "c/2")
    lines: list[str] = []

    def forge_of(name: str) -> tuple[Forge, RepoId]:
        if name == "platform":
            raise RuntimeError("host unreachable")
        return forge, REPO

    sweep([broken, fine], verdicts, forge, app, log=lines, forge_of=forge_of)

    recorded = read(verdicts)
    assert recorded["c/2"]["outcome"] == "clean"
    assert "outcome" not in recorded["c/1"]
    assert any("c/1" in line and "host unreachable" in line for line in lines)


def test_the_file_is_replaced_atomically(app: Path, forge: StandInForge, verdicts: Path) -> None:
    unit = merged("c/1", 1, timedelta(days=1))
    land(forge, app, 1)
    write(verdicts, "c/1")
    inode = verdicts.stat().st_ino

    sweep([unit], verdicts, forge, app)

    assert verdicts.stat().st_ino != inode
    assert read(verdicts)["c/1"]["outcome"] == "clean"
    assert not [p for p in verdicts.parent.iterdir() if p.name.endswith(".tmp")]
