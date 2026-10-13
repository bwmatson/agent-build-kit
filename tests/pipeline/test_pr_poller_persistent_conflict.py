"""A conflict that stands after the unit's own push is offered to the handler.

The poller has no store of attempts: it reports a definite conflicting answer
read after the unit's push, every poll, and the handler decides.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import HeldBy, ReworkKind
from agent_build_kit.pipeline.units import FAILED, HELD, PLANNED, RUNNING, SATISFIED
from tests.pr_poller_fakes import PollerRig, in_review_unit


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PollerRig:
    return PollerRig(tmp_path, monkeypatch, in_review_unit())


def test_a_conflict_read_after_the_push_is_offered_without_a_transition(rig: PollerRig) -> None:
    rig.poll(False)
    rig.push()

    rig.poll(False)

    assert rig.names() == ["conflict"]


def test_a_conflict_read_before_the_push_is_not_offered(rig: PollerRig) -> None:
    rig.poll(False)
    rig.push()

    rig.poll(None)

    assert rig.names() == []
    assert rig.seen()["mergeable_at"] is not None


def test_an_undetermined_answer_after_a_push_over_a_recorded_conflict_is_not_offered(
    rig: PollerRig,
) -> None:
    rig.poll(False)
    rig.poll(False)
    rig.push()

    rig.poll(None)
    rig.poll(None)

    assert rig.names() == []
    assert rig.seen()["mergeable_at"] is not None


@pytest.mark.parametrize("state", [RUNNING, PLANNED, FAILED, SATISFIED, HELD])
def test_a_unit_that_is_not_in_review_is_not_offered_a_conflict(rig: PollerRig, state) -> None:
    assert rig.unit is not None
    rig.unit = rig.unit.model_copy(update={"state": state, "held_by": HeldBy.REVIEW})
    rig.poll(False)
    rig.push()

    rig.poll(False)

    assert rig.names() == []
    assert rig.seen()["mergeable"] is False
    assert rig.seen()["mergeable_at"] is not None


def test_a_pull_request_with_no_unit_is_not_offered_a_conflict(rig: PollerRig) -> None:
    rig.poll(False)
    rig.unit = None

    rig.poll(False)

    assert rig.names() == []
    assert rig.seen()["mergeable_at"] is not None


def test_the_transition_still_sends_the_conflict_rework(rig: PollerRig) -> None:
    rig.poll(True)
    rig.push()

    rig.poll(False)

    assert [(event, kw["reason"], kw["rework"]) for event, kw in rig.events] == [
        ("rework", "merge conflict with its base", ReworkKind.CONFLICT)
    ]
    assert rig.seen()["mergeable_at"] is not None


def test_first_sight_still_sends_the_conflict_rework(rig: PollerRig) -> None:
    rig.path.write_text("{}")

    rig.poll(False)

    assert [(event, kw["reason"], kw["rework"]) for event, kw in rig.events] == [
        ("rework", "merge conflict with its base", ReworkKind.CONFLICT)
    ]
    assert rig.seen()["mergeable_at"] is not None


def test_an_event_that_is_not_taken_is_offered_again_next_poll(rig: PollerRig) -> None:
    rig.taken = False
    rig.poll(False)
    rig.push()

    rig.poll(False)
    rig.poll(False)

    assert rig.names() == ["conflict", "conflict"]
