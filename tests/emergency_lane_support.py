"""What the emergency-lane round tests share: a workspace with the lane's cap, a store seeded
with units in given states, and a round run over them."""

from __future__ import annotations

from collections.abc import Collection, Sequence
from pathlib import Path

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import emergency_lane
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING, UnitState
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.project_workspace import repos_declaring


def lane_workspace(
    tmp_path: Path,
    *,
    extra: int = 1,
    workers: int = 4,
    places: int = 5,
    restacks: int = 2,
    repos: dict | None = None,
) -> Installation:
    """One project with the limits of the lane tests: five places, four workers, a lane of one.
    A workspace with the repos `app` and `platform` unless `repos` says otherwise."""
    return make_installation(
        tmp_path,
        **({} if repos is None else {"repos": repos}),
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        project_limits={
            "max_concurrent_stacks": workers,
            "max_units_in_progress": places,
            "max_concurrent_restacks": restacks,
            "emergency_extra": extra,
        },
    )


def build(uid: str, state: UnitState = RUNNING, **fields: object) -> tuple[StoredUnit, UnitState]:
    """A unit in `state` that has begun (it has a branch), with a pull request when in review."""
    pr = {"pr": 1} if state == IN_REVIEW else {}
    return new_unit(uid, branch=f"spec/{uid}", **pr, **fields), state


def fresh(uid: str, **fields: object) -> tuple[StoredUnit, UnitState]:
    """A planned unit that has never started."""
    return new_unit(uid, **fields), PLANNED


def seeded(
    inst: Installation,
    tmp_path: Path,
    units: Sequence[tuple[StoredUnit, UnitState]],
    *,
    lane: Collection[str] = (),
) -> UnitStore:
    """A store holding `units` in the states given, with `lane` recorded as the units in the
    emergency lane. A unit that has a branch keeps it."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit for unit, _ in units])
    for unit, state in units:
        if state != PLANNED or unit.branch:
            store.set_state(unit.id, state, branch=unit.branch, pr=unit.pr)
    for unit_id in lane:
        emergency_lane.enter(inst.state_dir, store.get(unit_id))
    return store


def started_by_round(
    inst: Installation, store: UnitStore, *, building: Collection[str]
) -> list[str]:
    """The ids `run_round` hands out to start, with `building` as the builds in flight."""
    ready = cli.run_round(inst, store, building=building, only=frozenset(), submit=True)
    return [unit.id for unit in ready]


def app_only_repos(root: Path) -> dict:
    """The `repos` of a workspace with one project: `app`, without `platform`."""
    repos = repos_declaring(root)
    del repos["platform"]
    return repos
