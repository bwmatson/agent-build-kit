"""A conflict rework that changes nothing is not a resolution, whatever was recorded before.

The run ends with the unit back in review at the head it had; the conflict the host still
reports after it holds the unit with the reason, and nothing is dispatched a third time.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.pr_poller import CONFLICT_REASON, Poller
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, ReworkKind
from agent_build_kit.pipeline.units import HELD
from tests.conflict_event_fakes import PR, UNIT, ConflictRig
from tests.pr_poller_fakes import pull


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ConflictRig:
    return ConflictRig(tmp_path, monkeypatch)


def test_a_rework_that_changed_nothing_and_a_conflict_still_reported_holds_the_unit(
    rig: ConflictRig,
) -> None:
    rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT)
    rig.back_in_review("h1")

    rig.conflict()

    stored = rig.stored()
    assert (stored.state, stored.held_by) == (HELD, HeldBy.REVIEW)
    assert "changed nothing" in stored.note
    assert stored.cause is not Cause.REWORK, "it is not sent back a second time"


def test_no_third_dispatch_follows_a_rework_that_changed_nothing(rig: ConflictRig) -> None:
    rig.rework(CONFLICT_REASON, ReworkKind.CONFLICT)
    rig.back_in_review("h1")
    rig.conflict()

    rig.conflict()
    rig.conflict()

    assert rig.restacked == []
    stored = rig.stored()
    assert stored.state == HELD
    assert stored.conflict_attempts == 1


def test_a_conflict_recorded_since_before_the_rework_is_not_the_proof_it_is_gone(
    rig: ConflictRig,
) -> None:
    """Driven through the poller: its snapshot has said `false` since before the rework, and
    the poll after the run still offers the conflict, with no transition, and holds the unit."""
    answer: list[bool | None] = [True]
    offered: list[str] = []

    def dispatch(event: str, number: int, **kwargs) -> bool:
        offered.append(event)
        return rig.dispatch()(event, number, repo="app", **kwargs)

    poller = Poller(
        repo="app",
        state_path=rig.state_dir / "poll.json",
        list_prs=lambda: [pull(answer[0], PR)],
        dispatch=dispatch,
        unit_of=lambda number: rig.store.get(UNIT),
    )

    def poll(mergeable: bool | None) -> None:
        rig.clock.advance(300)
        answer[0] = mergeable
        poller.poll()

    poll(True)
    poll(False)
    assert offered == ["rework"], "the transition sent the conflict rework"
    rig.back_in_review("h1")
    offered.clear()

    poll(False)

    assert offered == ["conflict"], "no transition, and the event is still offered"
    stored = rig.stored()
    assert (stored.state, stored.held_by) == (HELD, HeldBy.REVIEW)
    assert "changed nothing" in stored.note
