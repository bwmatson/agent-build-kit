"""What the tests of a moved-base run and the slot occupancy share: a workspace of one project,
a real restack lane over runs that block until released, and rounds run over it.

A run is the work handed to the lane with no claim (`claimed=False`, as a run takes the branch
lock itself), so the lane holds one of its workers for as long as the test leaves it blocked.
Nothing here waits on the clock: a run begins when its event says so.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Sequence
from functools import partial
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.restack_lane import RestackLanes
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, ProjectKey, UnitState, project_key
from agent_build_kit.pipeline.wait_log import DECISIONS_NAME
from tests.emergency_lane_support import seeded
from tests.restack_lane_fakes import WAIT, Restacks, repo_behind
from tests.tick_pass import isolate


class Slots:
    """`units` in a store, a lane of `restacks` workers, and a cap of `cap` build workers. A
    unit in `flagged` carries the moved-base flag, as a unit whose run the lane makes does."""

    def __init__(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        units: Sequence[tuple[StoredUnit, UnitState]],
        *,
        cap: int = 4,
        restacks: int = 2,
        places: int = 50,
        flagged: Collection[str] = (),
    ) -> None:
        self.inst: Installation = repo_behind(
            tmp_path,
            monkeypatch,
            max_concurrent_stacks=cap,
            max_concurrent_restacks=restacks,
            max_units_in_progress=places,
        )
        isolate(monkeypatch)
        self.store: UnitStore = seeded(self.inst, tmp_path, units)
        for unit_id in flagged:
            self.store.set_moved_base_run(unit_id, True)
        self.runs = Restacks()
        self.lanes: RestackLanes = cli.build_restack_lane(self.inst, self.store)

    def hand_over(self, *unit_ids: str) -> None:
        """Hand each unit's run to the lane; those the lane has a worker for begin."""
        for unit_id in unit_ids:
            unit = self.store.get(unit_id)
            self.lanes.hand_over(unit, partial(self.runs, unit), claimed=False)

    def run(self, *unit_ids: str) -> None:
        """Hand the runs over and return once each has begun in a lane worker."""
        self.hand_over(*unit_ids)
        for unit_id in unit_ids:
            assert self.runs.begun[unit_id].wait(WAIT), unit_id + " never began"

    def end(self, *unit_ids: str) -> None:
        """End the runs: the units leave `running` as a run's end leaves them."""
        for unit_id in unit_ids:
            self.store.set_state(unit_id, IN_REVIEW, pr=9)
            self.runs.release(unit_id)
        while set(unit_ids) & {*self.lanes.running}:
            self.lanes.finished().result(WAIT)

    def occupancy(self, building: Collection[str] = (), of: str = "") -> set[str]:
        """The ids occupying the project of `of` (any unit of it; the first unit by default)."""
        units = self.store.all()
        key: ProjectKey = project_key(self.store.get(of) if of else units[0])
        # As the round does: work waiting behind the lane's cap holds no slot.
        waiting = set(self.lanes.waiting)
        counted = [unit for unit in units if unit.id not in waiting]
        return cli.slot_occupancy(counted, building, self.lanes.running).get(key, set())

    def started(self, building: Collection[str] = ()) -> list[str]:
        """The ids a round hands out to start, with `building` as the builds in flight."""
        ready = cli.run_round(
            self.inst,
            self.store,
            building=building,
            only=frozenset(),
            submit=True,
            lane=self.lanes,
        )
        return [unit.id for unit in ready]

    def reasons(self) -> dict[str, str]:
        """Each unit's latest recorded reason for waiting."""
        latest: dict[str, str] = {}
        for line in (self.inst.state_dir / DECISIONS_NAME).read_text().splitlines():
            record = json.loads(line)
            latest[record["unit"]] = record["reason"]
        return latest

    def __enter__(self) -> Slots:
        return self

    def __exit__(self, *exc: object) -> None:
        self.runs.release_all()
        self.lanes.drain()
