"""A worker killed mid-node leaves its lock stale, and the next worker resumes the unit at the node
its thread was in, from the checkpoint (spec: unit-workers). The real graph runs over the tick
driver's fake edges."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from agent_build_kit.cli.worker import cmd_worker_build
from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING, branch_name
from agent_build_kit.pipeline.workspaces import branch_held
from tests.branch_lock_fakes import dead_pid, lock_held_by
from tests.factories import unit as unit_factory
from tests.runner_fakes import Killed
from tests.tick_driver import UNIT, Setup, make_setup


@pytest.fixture
def graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    return make_setup(tmp_path, monkeypatch)


def worker(setup: Setup) -> int:
    return cmd_worker_build(argparse.Namespace(unit=UNIT), setup.inst)


def test_a_worker_resumes_a_killed_workers_unit_from_its_checkpoint(graph: Setup) -> None:
    graph.recorder.kill_after = "commit:feat"
    with pytest.raises(Killed):
        worker(graph)
    assert graph.next() == (Node.IMPLEMENT,)
    assert graph.store.get(UNIT).state == RUNNING
    branch = branch_name(unit_factory())
    lock_held_by(graph.inst, branch, dead_pid())
    assert not branch_held(branch, root=graph.inst.locks_dir)

    code = worker(graph)

    stored = graph.store.get(UNIT)
    assert code == 0
    assert stored.state == IN_REVIEW
    assert graph.recorder.events.count("claude:impl") == 1, "the finished step was not repeated"
    states = [entry.get("state") for entry in stored.history]
    assert states == [PLANNED, RUNNING, IN_REVIEW], "never put back to planned"
    assert graph.next() == (Node.AWAIT_REVIEW,)
