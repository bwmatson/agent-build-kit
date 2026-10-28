"""A unit no run holds that is paused for usage (`no_worker` of `ready_units`) is in progress and
takes no worker (spec: usage-pause-slots), also when it is in the emergency lane."""

from __future__ import annotations

from agent_build_kit.pipeline.units import PLANNED, RUNNING, ready_units
from tests.factories import new_unit as new
from tests.factories import worked_unit as worked


def starts(graph, *, workers: int, places: int, **kwargs) -> list[str]:
    return [
        unit.id
        for unit in ready_units(
            graph,
            max_concurrent=workers,
            depth_cap=9,
            max_units_in_progress=places,
            **kwargs,
        )
    ]


def test_a_paused_unit_takes_no_worker_so_a_planned_unit_starts() -> None:
    graph = [worked("paused/1", state=RUNNING), new("next/1")]

    assert starts(graph, workers=1, places=5, no_worker={"paused/1"}) == ["next/1"]
    # With the worker held by it the unit would wait, which is what an ordinary run does.
    assert starts(graph, workers=1, places=5) == []


def test_a_paused_unit_still_holds_a_place_of_the_limit() -> None:
    graph = [worked("paused/1", state=RUNNING), new("next/1")]

    assert starts(graph, workers=4, places=1, no_worker={"paused/1"}) == []
    assert starts(graph, workers=4, places=2, no_worker={"paused/1"}) == ["next/1"]


def test_a_paused_lane_unit_is_not_taken_off_the_workers_twice() -> None:
    """One worker, held by an ordinary run; the lane's unit is paused and holds none. A rework
    already started is held to the workers the lane's units leave, so it still waits."""
    graph = [
        worked("run/1", state=RUNNING),
        worked("lane/1", state=RUNNING, priority=0),
        worked("rework/1", state=PLANNED, pr=9, feedback="rework"),
    ]

    assert (
        starts(
            graph, workers=1, places=9, emergency_extra=1, in_lane=["lane/1"], no_worker={"lane/1"}
        )
        == []
    )
