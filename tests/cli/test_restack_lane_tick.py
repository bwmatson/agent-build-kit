"""A tick and a restack a resolve worker runs: the run takes no build slot of its own, so a
ready unit starts in a free slot beside it, and the tick ends without waiting for the run.

A tick is driven as `test_tick_samples` drives it; the worker's run is its record, which the
tick reads and never waits for.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.resolution_lane import lane_held_by_record, write_worker_record
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING, project_key
from agent_build_kit.pipeline.usage_guard import Decision
from tests.conftest import make_installation
from tests.factories import new_unit
from tests.time_limit import LOADED_TEST_TIME_LIMIT

# The tests of this module run whole passes, whose time depends on the machine's load.
pytestmark = [
    pytest.mark.usefixtures("scripted_engine"),
    pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT),
]


class Scene:
    """A workspace of two build slots and a build that notes itself: `second/1` is in review
    and a resolve worker (this process) is restacking it."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.inst: Installation = make_installation(
            tmp_path,
            planning={
                "state_dir": ".",
                "worktree_root": str(tmp_path.with_name(tmp_path.name + "-trees")),
            },
            project_limits={"max_concurrent_stacks": 2, "max_units_in_progress": 50},
        )
        self.store = UnitStore(tmp_path / "units.json")
        self.store.upsert([new_unit("first/1"), new_unit("second/1")])
        self.store.set_state("second/1", IN_REVIEW, pr=9, branch="spec/second/1")
        second = self.store.get("second/1")
        write_worker_record(self.inst.state_dir, project_key(second), second, base="main")
        self.started: list[str] = []
        for name, step in {
            "fetch_all": lambda inst: None,
            "plan_all": lambda inst, **kwargs: None,
            "has_identity": lambda inst, repo: True,
            "verify_ready": lambda inst, units, **kwargs: lambda change: True,
            "archive_ready_changes": lambda *a, **k: [],
            "current_usage": lambda: None,
            "may_start_unit": lambda r: Decision(may_start=True, reason="plenty"),
            "poll_all": lambda inst, **kwargs: None,
            "build_runner": lambda unit, **kwargs: self,
        }.items():
            monkeypatch.setattr(cli, name, step)

    def run(self, unit: StoredUnit, *, base: str, graph: list[StoredUnit]) -> RunOutcome:
        self.started.append(unit.id)
        self.store.set_state(unit.id, RUNNING, branch=f"spec/{unit.id}")
        self.store.set_state(unit.id, IN_REVIEW, pr=len(self.started))
        return RunOutcome(status=RunStatus.OPEN, detail=unit.id, pr=len(self.started))

    def tick(self) -> int:
        return cli.cmd_tick(argparse.Namespace(dry_run=False), self.inst)


@pytest.fixture
def scene(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Scene:
    return Scene(tmp_path, monkeypatch)


def test_a_build_slot_is_free_while_a_resolve_worker_restacks_and_a_ready_unit_starts_in_it(
    scene: Scene,
) -> None:
    assert scene.tick() == 0

    assert scene.started == ["first/1"]
    assert lane_held_by_record(scene.inst.state_dir) == {"second/1"}, "the run is left going"
