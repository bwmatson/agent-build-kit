"""A chat's commit reaches a unit's thread as the `adopted` event: it enters at the checks from
a unit in review, held or failed, never reuses the previous approval, gives the checks their own
fix budget, clears the recorded node start, and its review is round zero of the review loop
(docs/unit-graph.md, Events become resume commands)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from agent_build_kit.graph.checkpointer import open_checkpointer, unit_graphs_path
from agent_build_kit.graph.state import EventKind, Node, ResumeEvent
from agent_build_kit.graph.unit import seed_thread
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW, RUNNING
from tests.factories import unit
from tests.graph.test_release_event import limited
from tests.graph_driver import fresh, position, tick
from tests.runner_fakes import Recorder

ADOPTED = ResumeEvent(kind=EventKind.ADOPTED, reason="a chat's commit")
FAILING = "lint: unused import"


def asks_for(change: str) -> str:
    return json.dumps({"approved": False, "feedback": change})


def parked(tmp_path: Path, how: str) -> Recorder:
    """The unit's thread waiting where `how` says: in review, held by a reviewer, or failed."""
    if how == "failed":
        limited(max_check_rounds=0)
        recorder = fresh(tmp_path, tier1_ok=False)
        recorder.tier1_output = FAILING
        assert tick(tmp_path, recorder).status == RunStatus.FAILED
        recorder.tier1_ok = True
        assert recorder.store.get(unit().id).state == FAILED
        return recorder
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder)
    if how == "held":
        tick(tmp_path, recorder, event=ResumeEvent(kind=EventKind.HOLD))
        assert recorder.store.get(unit().id).state == HELD
    return recorder


@pytest.mark.parametrize("how", ["in_review", "held", "failed"])
def test_adopted_enters_at_the_checks_from_every_stable_state(tmp_path: Path, how: str) -> None:
    recorder = parked(tmp_path, how)
    ran = list(recorder.events)

    tick(tmp_path, recorder, event=ADOPTED)

    assert position(tmp_path).next == (Node.CHECKS,)
    stored = recorder.store.get(unit().id)
    assert stored.state == RUNNING
    assert stored.cause == Cause.ADOPTED
    assert recorder.events == ran, "a delivery runs nothing; the tick does"


def test_adopted_does_not_reuse_the_previous_approval(tmp_path: Path) -> None:
    recorder = parked(tmp_path, "in_review")
    assert recorder.events.count("review") == 1
    tick(tmp_path, recorder, event=ADOPTED)
    approved = position(tmp_path).state
    assert approved is not None and not approved.head_approved

    outcome = tick(tmp_path, recorder)

    assert outcome.status == RunStatus.OPEN
    assert recorder.events.count("review") == 2, "the new head is reviewed"
    assert recorder.events.count("tier1") == 2, "and checked"
    assert recorder.store.get(unit().id).state == IN_REVIEW


def test_adopted_clears_the_recorded_node_start(tmp_path: Path) -> None:
    recorder = parked(tmp_path, "in_review")
    left = position(tmp_path).state
    assert left is not None

    async def kill_mid_node() -> None:
        async with open_checkpointer(unit_graphs_path(tmp_path / "state")) as saver:
            await seed_thread(
                saver,
                left.model_copy(update={"running_node": "implement"}),
                as_node=Node.AWAIT_REVIEW,
            )

    asyncio.run(kill_mid_node())
    marked = position(tmp_path).state
    assert marked is not None and marked.running_node == "implement"

    tick(tmp_path, recorder, event=ADOPTED)

    cleared = position(tmp_path).state
    assert cleared is not None and cleared.running_node == ""
    assert position(tmp_path).next == (Node.CHECKS,)


def test_the_checks_after_an_adopted_commit_have_their_own_fix_budget(tmp_path: Path) -> None:
    limited(max_check_rounds=1)
    recorder = fresh(tmp_path)
    recorder.tier1_results = [(False, FAILING), (True, "")]
    tick(tmp_path, recorder)
    assert recorder.events.count("claude:fix_checks") == 1, "the build spent its budget"
    recorder.tier1_results = [(False, FAILING), (True, "")]
    tick(tmp_path, recorder, event=ADOPTED)

    outcome = tick(tmp_path, recorder)

    assert outcome.status == RunStatus.OPEN
    assert recorder.events.count("claude:fix_checks") == 2, "a fix round of the chat's own"


def test_checks_that_keep_failing_after_an_adopted_commit_fail_the_unit_as_usual(
    tmp_path: Path,
) -> None:
    limited(max_check_rounds=1)
    recorder = parked(tmp_path, "in_review")
    recorder.tier1_ok = False
    recorder.tier1_output = FAILING
    tick(tmp_path, recorder, event=ADOPTED)

    outcome = tick(tmp_path, recorder)

    assert outcome.status == RunStatus.FAILED
    assert "checks still failing after 1 fix round(s)" in outcome.detail
    assert recorder.events.count("review") == 1, "no review of a failing head"
    assert recorder.store.get(unit().id).state == FAILED


# --- the review that follows is round zero ------------------------------------------------------


def spent(tmp_path: Path) -> Recorder:
    """A unit held for having spent its one review round."""
    limited(max_review_rounds=1)
    recorder = fresh(tmp_path)
    recorder.verdicts = [asks_for("rename the flag")]
    tick(tmp_path, recorder)
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.held_by) == (HELD, "review")
    return recorder


def test_the_review_after_an_adopted_commit_does_not_hold_a_unit_whose_budget_was_spent(
    tmp_path: Path,
) -> None:
    recorder = spent(tmp_path)
    tick(tmp_path, recorder, event=ADOPTED)

    outcome = tick(tmp_path, recorder)

    assert outcome.status == RunStatus.OPEN
    stored = recorder.store.get(unit().id)
    assert (stored.state, stored.held_by) == (IN_REVIEW, "")
    told = " ".join(recorder.contexts[-1].split()).lower()
    assert "round 1 of 1" not in told, "the round is not one of the limit"


def test_a_review_that_asks_for_changes_after_an_adopted_commit_is_reworked_not_held(
    tmp_path: Path,
) -> None:
    recorder = spent(tmp_path)
    kept = position(tmp_path).state
    assert kept is not None and kept.review_rounds, "the earlier findings"
    tick(tmp_path, recorder, event=ADOPTED)
    after = position(tmp_path).state
    assert after is not None and after.review_rounds == kept.review_rounds, "are kept"
    recorder.verdicts = [asks_for("rename it again")]

    tick(tmp_path, recorder)

    assert recorder.events.count("claude:rework") == 1, "the reviewer's ask is worked on"
    stored = recorder.store.get(unit().id)
    assert "rounds spent" not in stored.note
    state = position(tmp_path).state
    assert state is not None and state.review_round >= 1, "the counted rounds start at the rework"
