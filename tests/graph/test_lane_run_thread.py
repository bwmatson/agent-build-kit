"""A thread parked at `prepare` is run by the lane past it, to the next wait or the end, in the
unit's recorded build session (spec: unit-scheduling, the lane runs the whole moved-base run).

The scene is the one of `test_restack_lane_prepare`: the unit is `running` with `base_changed`
and its thread at `prepare`. What follows the move used to be left for a build worker; here the
lane's worker goes on, so the thread is read where it is left and from which worker each node ran.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_build_kit.graph.nodes import WAITS
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED
from tests.graph.agent_fakes import distinct_models
from tests.graph.test_adapt_in_the_restack_session import MISSING, Failing
from tests.graph.test_restack_lane_prepare import Scene
from tests.graph.test_session_continuation import Sessions, agents
from tests.tick_driver import OTHER, Setup


def test_the_lane_runs_the_thread_through_the_nodes_after_prepare_to_the_next_wait(
    graph: Setup, tmp_path: Path
) -> None:
    stages: list[tuple[str, bool]] = []
    scenes: list[Scene] = []

    def unit_test(**kwargs: Any) -> tuple[bool, str]:
        if scenes:
            stages.append(("unit_test", scenes[0].in_the_lane()))
        return graph.recorder.unit_test(**kwargs)

    graph.options["run_unit_test"] = unit_test
    scene = Scene(graph, tmp_path)
    scenes.append(scene)
    scene.told_its_base_moved()

    scene.lane_moves()

    assert stages == [("unit_test", True)], "the tests after the move ran in the lane's worker"
    stored = graph.store.get(OTHER)
    assert stored.state == IN_REVIEW
    ahead = graph.next(OTHER)
    assert ahead and set(ahead) <= WAITS, "left at a wait, as a worker's run leaves it"
    assert scene.offered() == [], "and no worker has anything left to start"
    assert graph.recorder.events.count("push") >= 1


def test_the_run_ports_a_conflict_the_steps_could_not_settle_in_the_session_they_ran_in(
    graph: Setup, tmp_path: Path
) -> None:
    distinct_models()
    runtime = Sessions()
    graph.options.update(agents(runtime))
    scene = Scene(graph, tmp_path)
    graph.options["restack_onto"] = scene.restack(Failing())
    graph.options["reset_to"] = lambda tree, onto, keep: None
    graph.options["tests_in"] = lambda tree: {MISSING}
    graph.options["tests_changed"] = lambda tree, ref: set()
    scene.told_its_base_moved()
    before = len(runtime.requests)

    scene.lane_moves()

    asked = [request for request in runtime.built if request in runtime.requests[before:]]
    assert len(asked) == 3, "the two steps, then the port the lane's worker made"
    *steps, port = asked
    assert port.resume_session == steps[-1].resume_session != ""
    assert graph.store.get(OTHER).state != PLANNED, "not left for a build worker"
