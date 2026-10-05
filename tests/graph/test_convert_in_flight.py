"""A store left by the classic engine converts to threads positioned at the
nodes the design names, and each unit then proceeds as it would have
(docs/unit-graph.md, Moving the units in flight)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.convert import convert_units_in_flight
from agent_build_kit.graph.state import EventKind, Node, ResumeEvent
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED, RUNNING, branch_name
from tests.classic_store import leave_in_flight
from tests.factories import unit
from tests.graph_driver import position, run_on_graph, tick
from tests.runner_fakes import Recorder, make_runner

UNIT = "add-marker/1"
WAITING = "rename the marker"


def stored(
    tmp_path: Path,
    *,
    state: str = PLANNED,
    resume_from: str = "",
    feedback: str = "",
    pr: int | None = None,
    tier: str = "tier1",
    **in_run: Any,
) -> Recorder:
    """A store as the previous engine left it, with a commit on the branch."""
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit(tier=tier)])
    store.set_state(UNIT, state, pr=pr, branch=branch_name(unit()))
    leave_in_flight(store, UNIT, resume_from=resume_from, **in_run)
    if feedback:
        store.set_feedback(UNIT, feedback, from_person=True)
    recorder = Recorder(store)
    recorder.made = 2
    return recorder


def convert(tmp_path: Path, store: UnitStore) -> tuple[str, ...]:
    async def go() -> tuple[str, ...]:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            return await convert_units_in_flight(saver, store)

    return asyncio.run(go())


@pytest.mark.parametrize(
    ("step", "node"),
    [
        ("tests", Node.TESTS),
        ("implement", Node.IMPLEMENT),
        ("review", Node.REVIEW),
        ("rework_review", Node.REVIEW),
        ("verify", Node.VERIFY_BASE),
        ("restack", Node.PREPARE),
    ],
)
def test_a_unit_stopped_before_a_step_gets_a_thread_at_the_node_that_step_names(
    tmp_path: Path, step: str, node: Node
) -> None:
    recorder = stored(tmp_path, resume_from=step)

    assert convert(tmp_path, recorder.store) == (UNIT,)

    where = position(tmp_path)
    assert where.next == (node,)
    assert where.state is not None
    assert where.state.unit_id == UNIT


def test_a_unit_with_waiting_feedback_gets_a_thread_at_rework(tmp_path: Path) -> None:
    recorder = stored(tmp_path, feedback=WAITING)

    assert convert(tmp_path, recorder.store) == (UNIT,)

    assert position(tmp_path).next == (Node.REWORK,)


def test_a_unit_in_review_gets_a_thread_already_waiting_in_await_review(tmp_path: Path) -> None:
    recorder = stored(tmp_path, state=IN_REVIEW, pr=7)

    assert convert(tmp_path, recorder.store) == (UNIT,)

    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_held_unit_gets_a_thread_already_waiting_in_held(tmp_path: Path) -> None:
    recorder = stored(tmp_path, state=HELD)

    assert convert(tmp_path, recorder.store) == (UNIT,)

    assert position(tmp_path).next == (Node.HELD,)


def test_a_unit_with_nothing_in_flight_gets_no_thread(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])

    assert convert(tmp_path, store) == ()

    assert position(tmp_path).state is None


def test_converting_twice_leaves_the_threads_where_they_are(tmp_path: Path) -> None:
    recorder = stored(tmp_path, resume_from="review")
    convert(tmp_path, recorder.store)
    tick(tmp_path, recorder)
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)

    assert convert(tmp_path, recorder.store) == ()

    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_unit_converted_at_review_is_reviewed_and_goes_on_without_building(
    tmp_path: Path,
) -> None:
    recorder = stored(tmp_path, resume_from="review")
    convert(tmp_path, recorder.store)

    outcome = tick(tmp_path, recorder)

    assert outcome.status == RunStatus.OPEN
    assert recorder.events.count("review") == 1
    assert "claude:impl" not in recorder.events
    assert "claude:tests" not in recorder.events
    assert recorder.pr_opens == 1
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_unit_converted_at_verify_skips_review_and_pushes(tmp_path: Path) -> None:
    recorder = stored(tmp_path, resume_from="verify")
    recorder.store.record_approval(UNIT, recorder.head(tmp_path))
    convert(tmp_path, recorder.store)

    tick(tmp_path, recorder)

    assert "review" not in recorder.events
    assert recorder.events.count("push") == 1
    assert recorder.pr_opens == 1
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_unit_converted_with_waiting_feedback_reworks_it_once(tmp_path: Path) -> None:
    recorder = stored(tmp_path, feedback=WAITING)
    convert(tmp_path, recorder.store)

    tick(tmp_path, recorder)

    assert recorder.events.count("claude:rework") == 1
    assert WAITING in recorder.prompts[-1]
    assert "claude:impl" not in recorder.events
    assert recorder.store.get(UNIT).feedback == "", "acted on once"
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_comment_on_a_converted_unit_in_review_resumes_it_into_rework(tmp_path: Path) -> None:
    recorder = stored(tmp_path, state=IN_REVIEW, pr=7)
    convert(tmp_path, recorder.store)

    tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.REWORK, feedback=WAITING))
    assert position(tmp_path).next == (Node.REWORK,)
    tick(tmp_path, recorder)

    assert WAITING in recorder.prompts[-1]
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_converted_held_unit_is_requeued_into_prepare(tmp_path: Path) -> None:
    recorder = stored(tmp_path, state=HELD)
    convert(tmp_path, recorder.store)

    tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.REQUEUE))

    assert position(tmp_path).next == (Node.PREPARE,)


def test_a_merge_for_a_converted_unit_in_review_ends_its_thread(tmp_path: Path) -> None:
    recorder = stored(tmp_path, state=IN_REVIEW, pr=7)
    convert(tmp_path, recorder.store)

    tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.MERGED))

    assert position(tmp_path).state is None


def test_a_tier_2_unit_stopped_at_verify_runs_tier_2_before_it_pushes(tmp_path: Path) -> None:
    # The previous engine recorded `verify` before tier 2 ran, so a unit stopped
    # there, or killed during tier 2, has not passed it.
    recorder = stored(tmp_path, resume_from="verify", tier="tier2")
    recorder.store.record_approval(UNIT, recorder.head(tmp_path))
    convert(tmp_path, recorder.store)
    assert position(tmp_path).next == (Node.TIER2,)

    run_on_graph(make_runner(recorder.store, recorder, tmp_path), unit(tier="tier2"))

    assert "review" not in recorder.events
    assert recorder.events.count("tier2") == 1
    assert recorder.events.index("tier2") < recorder.events.index("push")
    assert position(tmp_path).next == (Node.AWAIT_REVIEW,)


def test_a_tier_1_unit_stopped_at_verify_goes_to_the_base_check(tmp_path: Path) -> None:
    recorder = stored(tmp_path, resume_from="verify")
    recorder.store.record_approval(UNIT, recorder.head(tmp_path))

    convert(tmp_path, recorder.store)

    assert position(tmp_path).next == (Node.VERIFY_BASE,)


def test_a_running_unit_with_no_step_and_no_feedback_gets_a_thread_at_prepare(
    tmp_path: Path,
) -> None:
    # Killed before its first step was recorded: during setup, the fetch, or a restack.
    recorder = stored(tmp_path, state=RUNNING)

    assert convert(tmp_path, recorder.store) == (UNIT,)

    assert position(tmp_path).next == (Node.PREPARE,)


def test_converting_moves_the_step_and_the_in_run_progress_into_the_thread(
    tmp_path: Path,
) -> None:
    recorder = stored(
        tmp_path,
        resume_from="review",
        pending_replies=["done"],
        person_comments="[comment 1] rename",
        deferred=["tidy the docs"],
        review_rounds=[{"asked": "rename it", "response": "renamed"}],
    )

    convert(tmp_path, recorder.store)

    state = position(tmp_path).state
    assert state is not None
    assert state.pending_replies == ("done",)
    assert state.person_comments == "[comment 1] rename"
    assert state.deferred == ("tidy the docs",)
    assert state.review_rounds == ({"asked": "rename it", "response": "renamed"},)
    after = recorder.store.get(UNIT)
    assert after.resume_from == "" and after.classic_run == {}, "nothing reads them again"


def test_a_store_an_older_version_wrote_still_loads_with_its_in_run_keys(tmp_path: Path) -> None:
    recorder = stored(tmp_path, pending_replies=["done"], review_rounds=[])

    loaded = recorder.store.get(UNIT)

    assert loaded.classic_run == {"pending_replies": ["done"]}
