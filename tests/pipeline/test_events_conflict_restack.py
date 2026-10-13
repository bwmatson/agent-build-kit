"""A conflicting unit's first attempt is the stack move; any other is the conflict rework.

The stack move is `build_restack`'s, over a fake git, tier 1 and host, so its outcomes are the
merge handler's own.
"""

from contextlib import contextmanager
from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack import Moved, RestackConflict
from agent_build_kit.pipeline.unit_store import Cause, ReworkKind
from agent_build_kit.pipeline.units import IN_REVIEW, PLANNED, local_ref
from agent_build_kit.pipeline.workspaces import BranchBusy
from tests.conflict_event_fakes import UNIT, ConflictRig, real_restack


def test_the_first_attempt_of_a_trunk_based_unit_is_the_stack_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)

    rig.conflict()

    (call,) = rig.restacked
    assert call["branch"] == "spec/add-marker/1"
    assert call["child"].id == UNIT
    assert call["new_base"] == "main"
    assert call["old_base"] == "fork1", "the fork point, not the trunk's new tip"
    assert call["old_base"] != local_ref("main", repo="app")
    assert call["parent"] is call["child"]
    assert rig.stored().state == IN_REVIEW


def test_a_clean_move_of_an_approved_head_is_pushed_and_stays_in_review(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    pushed: list[str] = []
    comments: list[str] = []
    rig.restack = real_restack(
        rig, tmp_path, move=lambda *a, **k: Moved(sha="n"), pushed=pushed, comments=comments
    )

    rig.conflict()

    assert pushed == ["pushed"]
    (body,) = comments
    assert f"{UNIT} merged" not in body
    assert "the trunk moved" in body
    stored = rig.stored()
    assert stored.state == IN_REVIEW
    assert stored.pushed == "newsha"
    assert stored.conflict_attempts == 1


@pytest.mark.parametrize(
    ("moved", "diff_changes"),
    [(Moved(sha="n", resolved=("a.py",)), False), (Moved(sha="n"), True)],
    ids=["resolved", "changed diff"],
)
def test_a_resolved_move_or_a_changed_diff_is_planned_for_review_unpushed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, moved: Moved, diff_changes: bool
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    pushed: list[str] = []
    rig.restack = real_restack(
        rig, tmp_path, move=lambda *a, **k: moved, pushed=pushed, diff_changes=diff_changes
    )

    rig.conflict()

    stored = rig.stored()
    assert (stored.state, stored.cause) == (PLANNED, Cause.RESTACK_DEFERRED)
    assert pushed == []
    assert stored.conflict_attempts == 1


def test_a_move_that_cannot_be_settled_goes_to_the_conflict_rework_and_counts_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)

    def cannot(*args, **kwargs):
        raise RestackConflict("a.py conflicts")

    rig.restack = real_restack(rig, tmp_path, move=cannot, pushed=[])

    rig.conflict()

    stored = rig.stored()
    assert (stored.state, stored.cause) == (PLANNED, Cause.REWORK)
    assert stored.conflict_attempts == 1


def test_a_second_attempt_at_the_same_tip_is_the_conflict_rework(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    moves: list[str] = []
    pushed: list[str] = []
    rig.restack = real_restack(
        rig, tmp_path, move=lambda *a, **k: moves.append("move") or Moved(sha="n"), pushed=pushed
    )
    rig.conflict()
    assert pushed == ["pushed"]

    rig.conflict()

    assert moves == ["move"], "the move is not made a second time"
    stored = rig.stored()
    assert (stored.state, stored.cause) == (PLANNED, Cause.REWORK)
    assert stored.conflict_attempts == 2


def test_a_stacked_unit_goes_to_the_conflict_rework(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch, stacked=True)

    rig.conflict()

    assert rig.restacked == []
    stored = rig.stored()
    assert (stored.state, stored.cause) == (PLANNED, Cause.REWORK)
    assert stored.conflict_attempts == 1


def test_a_unit_whose_thread_takes_the_event_goes_to_the_conflict_rework(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    delivered: list[tuple] = []

    def resume(unit, kind, reason, feedback, **kwargs):
        delivered.append((kind, kwargs.get("rework")))
        return True

    rig.resume = resume

    rig.conflict()

    assert rig.restacked == []
    assert delivered == [("rework", ReworkKind.CONFLICT)]
    assert rig.stored().conflict_attempts == 1


def test_a_held_branch_lock_leaves_the_event_for_the_next_poll_and_records_no_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    busy = {"on": True}

    @contextmanager
    def claim(unit):
        if busy["on"]:
            raise BranchBusy("being built")
        yield

    rig.claim = claim

    assert rig.conflict() is False
    stored = rig.stored()
    assert rig.restacked == []
    assert (stored.conflict_tip, stored.conflict_attempts) == ("", 0)

    busy["on"] = False
    assert rig.conflict() is True
    assert len(rig.restacked) == 1


def test_a_move_that_fails_is_the_attempt_and_is_not_made_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    moves: list[str] = []
    rig.restack = real_restack(
        rig,
        tmp_path,
        move=lambda *a, **k: moves.append("move") or Moved(sha="n"),
        pushed=[],
        tier1=lambda **kwargs: (False, "boom"),
    )

    assert rig.conflict() is True
    assert rig.stored().conflict_attempts == 1
    assert any("move failed" in line for line in rig.logged)

    assert rig.conflict() is True
    assert moves == ["move"], "the move is not made a second time"


def test_a_base_tip_that_cannot_be_read_ends_the_event_without_raising(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)

    def unread(unit):
        raise RuntimeError("no origin/main")

    rig.base_tip = unread

    assert rig.conflict() is True
    assert rig.restacked == []
    assert rig.stored().conflict_attempts == 0


def test_the_move_tells_tier_1_and_the_comment_which_base_it_left(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rig = ConflictRig(tmp_path, monkeypatch)
    moved_from: list[str] = []
    comments: list[str] = []

    def tier1(**kwargs):
        moved_from.append(kwargs["moved_from"])
        return True, ""

    rig.restack = real_restack(
        rig,
        tmp_path,
        move=lambda *a, **k: Moved(sha="n"),
        pushed=[],
        tier1=tier1,
        comments=comments,
    )

    rig.conflict()

    assert moved_from == ["fork1"]
    (body,) = comments
    assert "fork1" in body
