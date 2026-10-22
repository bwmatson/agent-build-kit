"""A unit over its earned tier's buffered ceiling is held as too big for its tier, which is
neither a failure nor a review round (spec: hold-and-split).

Each test drives the real graph with the real verdict: the fake runner reports the changed
lines, and the ceilings in the workspace decide whether the round's verdict is hold-and-split.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.graph.checkpointer import unit_graphs_path
from agent_build_kit.pipeline.unit_store import Cause, HeldBy
from agent_build_kit.pipeline.units import HELD
from tests.factories import activate_with, unit
from tests.graph.checkpoint_reads import read_back
from tests.graph.test_build_path import build, fresh
from tests.graph.test_remaining_paths import verdict
from tests.runner_fakes import Recorder, approving, rejecting

UNIT_ID = unit().id
# The unit earns `full` (the reviewer gives no classification): over 500 times 1.2 is held.
OVER = 2000
UNDER = 500


@pytest.fixture(autouse=True)
def small_ceilings() -> None:
    activate_with(review={"enabled": True, "ceilings": {"auto": 1000, "light": 800, "full": 500}})


def over(tmp_path: Path, reply: str, lines: int = OVER) -> Recorder:
    tmp_path.mkdir(exist_ok=True)
    recorder = fresh(tmp_path)
    recorder.changed_lines = lines
    recorder.verdicts = [reply]
    build(tmp_path, recorder)
    return recorder


def graph_state(tmp_path: Path) -> dict:
    return read_back(unit_graphs_path(tmp_path / "state"), UNIT_ID).values


@pytest.mark.parametrize(
    "reply", [approving(), rejecting("rename the lock")], ids=["approves", "asks"]
)
def test_a_round_whose_verdict_is_hold_and_split_holds_the_unit_at_once(
    tmp_path: Path, reply: str
) -> None:
    recorder = over(tmp_path, reply)

    stored = recorder.store.get(UNIT_ID)
    assert stored.state == HELD
    assert (stored.cause, stored.held_by) == (Cause.TOO_BIG_FOR_TIER, HeldBy.SIZE)
    assert recorder.events.count("review") == 1
    assert "claude:rework" not in recorder.events, "no rework round is started"


@pytest.mark.parametrize(
    "reply", [approving(), rejecting("rename the lock")], ids=["approves", "asks"]
)
def test_the_request_holds_the_tiers_lines_ceiling_and_drivers(tmp_path: Path, reply: str) -> None:
    named = json.loads(reply) | {"drivers": ["group 1"]}

    recorder = over(tmp_path, json.dumps(named))

    request = recorder.store.get(UNIT_ID).split_request
    assert request is not None
    assert (request.earned, request.lines, request.ceiling) == ("full", OVER, 500)
    assert request.drivers == (1,)


def test_the_review_round_and_the_rework_count_are_as_before(tmp_path: Path) -> None:
    over(tmp_path, rejecting("rename the lock"))

    state = graph_state(tmp_path)
    assert state["review_round"] == 0
    assert state["fix_rounds"] == 0


@pytest.mark.parametrize(
    "reply", [approving(), rejecting("rename the lock")], ids=["approves", "asks"]
)
def test_the_unit_is_not_failed_and_nothing_is_pushed_or_opened(tmp_path: Path, reply: str) -> None:
    recorder = over(tmp_path, reply)

    stored = recorder.store.get(UNIT_ID)
    assert stored.state != "failed"
    assert stored.pr is None
    assert "push" not in recorder.events
    assert "pr" not in recorder.events
    assert recorder.prs == {}


def test_a_unit_at_the_buffered_ceiling_goes_on_where_one_over_it_is_held(tmp_path: Path) -> None:
    held = over(tmp_path / "over", approving(), lines=600 + 1)
    kept = over(tmp_path / "at", approving(), lines=600)

    assert held.store.get(UNIT_ID).cause == Cause.TOO_BIG_FOR_TIER
    stored = kept.store.get(UNIT_ID)
    assert stored.cause != Cause.TOO_BIG_FOR_TIER
    assert stored.split_request is None
    assert "push" in kept.events


def test_a_round_whose_reply_holds_the_unit_for_a_person_is_not_also_held_by_size(
    tmp_path: Path,
) -> None:
    sized = over(tmp_path / "size", approving())
    person = over(tmp_path / "person", verdict("exclude the file", needs_human=True))

    assert sized.store.get(UNIT_ID).held_by == HeldBy.SIZE
    stored = person.store.get(UNIT_ID)
    assert stored.state == HELD
    assert (stored.cause, stored.held_by) == (Cause.NEEDS_HUMAN, HeldBy.REVIEW)
    assert stored.split_request is None


def test_a_waived_unit_over_the_ceiling_is_not_held_for_its_size(tmp_path: Path) -> None:
    tmp_path.mkdir(exist_ok=True)
    recorder = fresh(tmp_path)
    recorder.changed_lines = OVER
    recorder.verdicts = [approving()]
    recorder.store.set_size_waived(UNIT_ID)

    build(tmp_path, recorder)

    stored = recorder.store.get(UNIT_ID)
    assert stored.cause != Cause.TOO_BIG_FOR_TIER
    assert stored.split_request is None
    assert "push" in recorder.events
