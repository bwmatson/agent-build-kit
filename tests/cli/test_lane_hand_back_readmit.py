"""A running pass lets a unit the lane handed back in and starts it in a build worker; the lane's
scan leaves it to that worker (spec: unit-scheduling).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.state import Node
from agent_build_kit.pipeline.restack_lane import moved_base_units
from agent_build_kit.pipeline.units import FAILED, HELD
from tests.graph.test_restack_lane_prepare import Scene
from tests.lane_hand_back_support import handed_back_at, resolved_move
from tests.runner_fakes import rejecting
from tests.tick_driver import OTHER, Setup, make_setup


@pytest.fixture
def graph(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Setup:
    return make_setup(tmp_path, monkeypatch)


def test_a_pass_starts_a_handed_back_unit_in_a_build_worker_and_the_lane_does_not_list_it(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path)
    resolved_move(scene)
    graph.recorder.verdicts.append(rejecting("rename the marker"))
    scene.told_its_base_moved()
    before = graph.store.get(OTHER)

    scene.lane_moves()

    handed_back_at(scene, Node.REWORK)
    ready = cli.run_round(graph.inst, graph.store, building=(), only=frozenset(), submit=True)
    assert [unit.id for unit in ready] == [OTHER], "within the one build the cap allows"
    assert OTHER not in moved_base_units(graph.inst, graph.store.all())
    assert OTHER not in cli.owed_units(graph.inst, graph.store.all())
    after = graph.store.get(OTHER)
    assert (after.approved, after.pr, after.pushed) == (before.approved, before.pr, before.pushed)
    assert after.state not in (FAILED, HELD)


def test_a_unit_handed_back_with_no_feedback_is_not_the_lanes_and_a_build_worker_takes_it(
    graph: Setup, tmp_path: Path
) -> None:
    scene = Scene(graph, tmp_path, tier="e2e-test")
    scene.told_its_base_moved()

    scene.lane_moves()

    handed_back_at(scene, Node.E2E)
    assert not graph.store.get(OTHER).feedback, "nothing of its own to rework"
    assert OTHER not in cli.owed_units(graph.inst, graph.store.all())
    ready = cli.run_round(graph.inst, graph.store, building=(), only=frozenset(), submit=True)
    assert [unit.id for unit in ready] == [OTHER]
