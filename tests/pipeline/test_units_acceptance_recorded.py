"""A recorded store, reduced to its direct dependencies, waits for what it did unreduced.

The store under `tests/fixtures/stores` is written the way the pipeline writes one: chains
that list every ancestor, an independent unit, a unit in another repository, and acceptance
and narrow units that list everything before them. It is loaded read-only and reduced in
memory by a stand-in written here; the acceptance and narrow units must wait for the same
units either way, in the recorded states and with each earlier unit set back in turn, and
`ready_units` must start the same units.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    UnitState,
    ready_units,
    waiting_on,
)

RECORDED = Path(__file__).parent.parent / "fixtures" / "stores" / "recorded_units.json"
LIMITS = (1, 2, 3, 5)
SWEEP = (PLANNED, RUNNING, FAILED, HELD, IN_REVIEW, MERGED)


def reduced(graph: list[StoredUnit]) -> list[StoredUnit]:
    """The graph with each unit's dependencies cut to those no other of them reaches."""
    index = {u.id: u for u in graph}

    def reaches(start: str, goal: str, seen: frozenset[str] = frozenset()) -> bool:
        if start in seen or start not in index:
            return False
        return any(
            dep == goal or reaches(dep, goal, seen | {start}) for dep in index[start].depends_on
        )

    return [
        u.model_copy(
            update={
                "depends_on": tuple(
                    dep
                    for dep in u.depends_on
                    if not any(other != dep and reaches(other, dep) for other in u.depends_on)
                )
            }
        )
        for u in graph
    ]


@pytest.fixture
def recorded(tmp_path: Path) -> list[StoredUnit]:
    copy = tmp_path / "units.json"
    shutil.copy(RECORDED, copy)
    copy.chmod(0o444)
    return UnitStore(copy).all()


def flagged(graph: list[StoredUnit]) -> list[StoredUnit]:
    return [u for u in graph if u.flag in ("acceptance", "narrow")]


def earlier(unit: StoredUnit, graph: list[StoredUnit]) -> list[StoredUnit]:
    number = int(unit.id.rsplit("/", 1)[1])
    return [
        u
        for u in graph
        if u.change == unit.change and u.id != unit.id and int(u.id.rsplit("/", 1)[1]) < number
    ]


def with_state(graph: list[StoredUnit], uid: str, state: UnitState) -> list[StoredUnit]:
    return [u.model_copy(update={"state": state}) if u.id == uid else u for u in graph]


def sweeps(graph: list[StoredUnit]):
    """The recorded graph, then one graph for each earlier unit of a flagged unit set to
    each state in turn."""
    yield graph
    seen: set[str] = set()
    for unit in flagged(graph):
        for before in earlier(unit, graph):
            if before.id in seen:
                continue
            seen.add(before.id)
            for state in SWEEP:
                yield with_state(graph, before.id, state)


def wait_names(graph: list[StoredUnit]) -> dict[str, set[str]]:
    return {u.id: {w.id for w in waiting_on(u, graph)} for u in flagged(graph)}


def test_flagged_units_wait_for_the_same_units_reduced_as_unreduced(
    recorded: list[StoredUnit],
) -> None:
    assert {u.flag for u in flagged(recorded)} == {"acceptance", "narrow"}
    assert reduced(recorded) != recorded
    for graph in sweeps(recorded):
        assert wait_names(reduced(graph)) == wait_names(graph)


def test_ready_units_is_unchanged_by_the_reduction(recorded: list[StoredUnit]) -> None:
    for graph in sweeps(recorded):
        for limit in LIMITS:

            def started(units: list[StoredUnit], limit: int = limit) -> list[str]:
                return [u.id for u in ready_units(units, max_concurrent=limit, depth_cap=9)]

            assert started(reduced(graph)) == started(graph)
