"""`abk status` and the slot occupancy tell a comment rework that overflowed into a build worker
from one running in the lane: it is resolving in a worker, it holds a slot, and it is not a lane
run (spec: resolution-lane, a full lane overflows into the ordinary workers).

The overflow run is a unit stored `running` as a comment rework whose branch a run holds and
that the lane does not hold.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource
from agent_build_kit.pipeline.units import RUNNING, project_key
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.cli.test_status_restacks import printed
from tests.emergency_lane_support import build
from tests.lane_run_slots import Slots
from tests.restack_lane_fakes import caused

pytestmark = pytest.mark.usefixtures("scripted_engine")


def test_the_occupancy_counts_a_comment_rework_running_in_a_worker_and_not_one_in_the_lane() -> (
    None
):
    def comment(unit_id: str):
        return caused(
            unit_id,
            RUNNING,
            Cause.REWORK,
            branch=f"spec/{unit_id}",
            feedback="[comment c1] remove this",
            feedback_source=FeedbackSource.REVIEW,
            moved_base_run=True,
        )

    in_the_lane, in_a_worker = comment("c1/1"), comment("c2/1")

    occupied = cli.slot_occupancy([in_the_lane, in_a_worker], ["c2/1"], ["c1/1"])

    assert occupied == {project_key(in_a_worker): {"c2/1"}}


def test_the_status_says_an_overflow_run_is_resolving_in_a_worker_and_counts_its_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    with Slots(tmp_path, monkeypatch, [build("c1/1"), build("c2/1")], restacks=1) as slots:
        slots.comment_runs("c1/1", "c2/1")
        slots.run("c1/1")
        capsys.readouterr()

        with branch_lock(slots.store.get("c2/1").branch, root=slots.inst.locks_dir):
            assert cli.cmd_status(argparse.Namespace(), slots.inst) == 0
            lines = printed(capsys)

    assert "resolving: 1 running, 0 waiting" in lines, "the worker's run is not a lane run"
    assert any(
        "c2/1" in line and "resolving a comment" in line and "in a worker" in line for line in lines
    )
    assert not any("c1/1" in line and "in a worker" in line for line in lines)
    assert any(line.startswith("slots: 1/4") for line in lines)
