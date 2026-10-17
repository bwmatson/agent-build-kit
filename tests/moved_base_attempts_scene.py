"""What the tests of a moved-base run's attempts share: `feature/3`, a unit whose branch is
behind `main`, handed to the lane's scan and run by a scripted engine.

The stack move leaves the unit planned for its restack conflict, as a move that could not be
merged does, and the run is `scripted_engine`'s: the `run` of what `build_runner` returns, in
the lane's worker. `ends` says how a run ends; a run that settles leaves the unit in review.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING
from tests.factories import git, new_unit
from tests.restack_lane_fakes import repo_behind

UNIT = "feature/3"
BRANCH = "spec/feature/3"
PUSHED = "c0ffee"


class Attempts:
    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.inst: Installation = repo_behind(tmp_path, monkeypatch)
        self.store = UnitStore(tmp_path / "units.json")
        self.store.upsert([new_unit(UNIT)])
        self.store.record_push(UNIT, PUSHED)
        repo = self.inst.checkouts["app"]
        git(repo, "checkout", "-q", BRANCH)
        (repo / "own.txt").write_text("own\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "the unit's own work")
        git(repo, "checkout", "-q", "main")
        self.ran: list[str] = []
        self.moved = 0
        self.transcript: Callable[[str], None] = print
        self.ends: Any = self.settles
        self.owe()
        for name, step in {
            "fetch_all": lambda inst: None,
            "has_identity": lambda inst, repo: True,
            "build_runner": self.runner_for,
            "build_restack": lambda **kwargs: self.move,
        }.items():
            monkeypatch.setattr(cli, name, step)

    def runner_for(self, unit: StoredUnit, **kwargs: Any) -> Attempts:
        """`build_runner`: the run keeps the callback an agent's output reaches the run log by."""
        self.transcript = kwargs["transcript"]
        return self

    @property
    def unit(self) -> StoredUnit:
        return self.store.get(UNIT)

    def owe(self) -> None:
        """The unit's base moved: it is planned with its branch behind, owed a run."""
        self.store.set_state(UNIT, PLANNED, cause=Cause.BASE_CHANGED, branch=BRANCH)

    def move(self, **kwargs: Any) -> None:
        if self.unit.state not in (PLANNED, IN_REVIEW):
            return
        self.store.set_state(UNIT, PLANNED, cause=Cause.RESTACK_CONFLICT, branch=BRANCH)

    def run(self, unit: StoredUnit, *, base: str, graph: list[StoredUnit]) -> RunOutcome:
        self.ran.append(unit.id)
        return self.ends(unit)

    def settles(self, unit: StoredUnit) -> RunOutcome:
        self.store.set_state(unit.id, IN_REVIEW, pr=9, branch=BRANCH)
        return RunOutcome(status=RunStatus.OPEN, detail=unit.id, pr=9)

    def stands(self, unit: StoredUnit) -> RunOutcome:
        """A run that ends with the conflict standing: planned, for a person or a worker."""
        self.store.set_state(unit.id, PLANNED, cause=Cause.RESTACK_CONFLICT, branch=BRANCH)
        return RunOutcome(status=RunStatus.OPEN, detail=unit.id, pr=9)

    def leaves_running(self, unit: StoredUnit) -> None:
        """What a run that is cut off leaves: the unit running, in the lane's hands."""
        self.store.set_state(unit.id, RUNNING, branch=BRANCH, cause=Cause.RESTACK_CONFLICT)

    def scan(self) -> None:
        with cli.build_restack_lane(self.inst, self.store) as lanes:
            lanes.scan(self.store.all())

    def run_again(self) -> None:
        """The unit is owed a run again, and the lane's scan sees it."""
        self.owe()
        self.scan()

    def tip(self) -> str:
        return git(self.inst.checkouts["app"], "rev-parse", "main").strip()

    def base_moves(self) -> None:
        repo = self.inst.checkouts["app"]
        self.moved += 1
        (repo / ("moved-" + str(self.moved) + ".txt")).write_text("m\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-qm", "the base moves")
