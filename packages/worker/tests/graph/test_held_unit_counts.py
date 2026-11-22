"""A unit a run held before a step has started, as far as the scheduler can tell.

The graph records no resume step: a hold writes `planned` with a note, and the
branch the run recorded when it began is what says work was done. The limit on
units in progress and the order a free slot is given in read that, so these
drive a unit through the graph to a hold and ask the scheduler about what the
run left.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, RUNNING, in_progress, ready_units
from tests.factories import stored_unit, unit
from tests.graph_driver import fresh, tick


def held_before_a_step(tmp_path: Path):
    """A unit whose run stopped at a boundary because its upstream went back."""
    recorder = fresh(tmp_path)
    tick(
        tmp_path,
        recorder,
        upstream_incomplete=lambda u: (
            Cause.UPSTREAM_WENT_BACK,
            "add-marker/0 went back for rework",
        ),
    )
    return recorder.store.get(unit().id)


def test_a_unit_held_before_a_step_for_its_upstream_does_not_count_while_it_waits(
    tmp_path: Path,
) -> None:
    held = held_before_a_step(tmp_path).model_copy(update={"depends_on": ("add-marker/0",)})
    upstream = stored_unit("add-marker/0", state=RUNNING)

    assert held.state == PLANNED and held.pr is None
    assert not in_progress(held, [upstream, held])


def test_a_unit_held_before_a_step_counts_once_its_upstream_is_back_in_review(
    tmp_path: Path,
) -> None:
    held = held_before_a_step(tmp_path).model_copy(update={"depends_on": ("add-marker/0",)})
    upstream = stored_unit("add-marker/0", state=IN_REVIEW, pr=3)

    assert in_progress(held, [upstream, held])


def test_a_unit_held_before_a_step_takes_a_place_in_the_limit(tmp_path: Path) -> None:
    held = held_before_a_step(tmp_path)
    graph = [held, stored_unit("other/1", change="other")]

    started = ready_units(graph, max_concurrent=5, depth_cap=10, max_units_in_progress=1)

    assert [u.id for u in started] == [held.id], "it resumes; the never-started unit has no room"


def test_a_unit_held_before_a_step_starts_ahead_of_a_never_started_one(tmp_path: Path) -> None:
    held = held_before_a_step(tmp_path)
    graph = [stored_unit("other/1", change="other"), held]

    started = ready_units(graph, max_concurrent=1, depth_cap=10, max_units_in_progress=5)

    assert [u.id for u in started] == [held.id]
