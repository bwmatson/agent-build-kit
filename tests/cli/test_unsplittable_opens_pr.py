"""A unit over its ceiling that cannot be split is sent on with the size rule waived, not held for
a person, unless `review.unsplittable` is `hold` (spec: unsplittable-size)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.planner import GroupTooLarge
from agent_build_kit.pipeline.unit_store import Cause, HeldBy
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED, Member
from tests.cli.replan_driver import Replan, enable_review
from tests.split_step_support import DEPENDENT, HELD_ID, correct, reply, scene

pytestmark = pytest.mark.usefixtures("scripted_engine")

# Each way a unit cannot be split, and a phrase its recorded reason carries.
REASONS = {
    "one group": "one group",
    "another change": "another change",
    "started dependent": DEPENDENT,
    "rounds used": "rounds used",
    "group too large": "group 3 is too large",
}


def unsplittable_scene(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, hold: bool = False
) -> Replan:
    """A held unit that cannot be split for the reason `kind` names."""
    if kind == "one group":
        run = scene(tmp_path, monkeypatch, groups=(1,), drivers=())
    elif kind == "another change":
        run = scene(tmp_path, monkeypatch, joined=(Member(change="other", groups=(1,)),))
    elif kind == "started dependent":
        run = scene(tmp_path, monkeypatch)
        run.store.set_state(DEPENDENT, IN_REVIEW, branch=f"spec/{DEPENDENT}", pr=18)
    elif kind == "rounds used":
        run = scene(tmp_path, monkeypatch, rounds=2, used=2)
    else:
        run = scene(tmp_path, monkeypatch)

        def too_large(**_: object) -> None:
            raise GroupTooLarge(REASONS[kind])

        monkeypatch.setattr(cli, "plan_round", too_large)
    run.runtime.answer = reply(*correct())
    if hold:
        enable_review(run, split_rounds=2, unsplittable="hold")
    return run


@pytest.mark.parametrize("kind", REASONS)
def test_an_unsplittable_unit_is_sent_on_with_the_size_rule_waived(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = unsplittable_scene(kind, tmp_path, monkeypatch)

    cli.split_held_units(run.inst, run.store)

    unit = run.store.get(HELD_ID)
    assert unit.state == PLANNED
    assert unit.held_by == HeldBy.NONE
    assert unit.size_waived
    assert REASONS[kind] in unit.unsplit_reason
    released = [e for e in unit.history if e.get("cause") == Cause.RELEASED]
    assert released
    assert "not split" in released[-1]["note"]
    assert REASONS[kind] in released[-1]["note"]


@pytest.mark.parametrize("kind", REASONS)
def test_a_second_pass_does_not_hold_it_again(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = unsplittable_scene(kind, tmp_path, monkeypatch)

    cli.split_held_units(run.inst, run.store)
    after_first = run.store.get(HELD_ID)
    cli.split_held_units(run.inst, run.store)

    assert after_first.size_waived
    assert run.store.get(HELD_ID) == after_first


@pytest.mark.parametrize("kind", REASONS)
def test_hold_keeps_the_old_behaviour_for_each_reason(
    kind: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = unsplittable_scene(kind, tmp_path, monkeypatch, hold=True)

    cli.split_held_units(run.inst, run.store)

    unit = run.store.get(HELD_ID)
    assert (unit.state, unit.held_by, unit.cause) == (HELD, HeldBy.REVIEW, Cause.TOO_BIG_FOR_TIER)
    assert not unit.size_waived
    assert not unit.unsplit_reason


def test_an_unsplittable_unit_proceeds_while_planning_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = unsplittable_scene("one group", tmp_path, monkeypatch)

    cli.split_held_units(run.inst, run.store, may_plan=False)

    unit = run.store.get(HELD_ID)
    assert unit.state == PLANNED
    assert unit.size_waived
    assert run.calls == 0


def test_a_unit_that_can_be_split_is_still_split(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = scene(tmp_path, monkeypatch)
    enable_review(run, split_rounds=2, unsplittable="open_pr")
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    unit = run.store.get(HELD_ID)
    assert unit.superseded_by
    assert not unit.size_waived
    assert not unit.unsplit_reason
