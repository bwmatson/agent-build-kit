"""A unit held for its size that cannot be split is held for a person with the reason and a card,
and a round is used only by a refused plan (spec: hold-and-split, a unit that cannot be split)."""

from __future__ import annotations

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.notify.cards import desired_cards
from agent_build_kit.notify.provider import CardKind
from agent_build_kit.pipeline.unit_store import Cause, HeldBy
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, Member
from tests.cli.replan_driver import Replan
from tests.split_step_support import DEPENDENT, HELD_ID, PIECES, correct, piece, reply, scene

pytestmark = pytest.mark.usefixtures("scripted_engine")

FIRST, SECOND, THIRD = PIECES


def assert_held_for_a_person(run: Replan, *words: str) -> None:
    held = run.store.get(HELD_ID)
    assert (held.state, held.held_by, held.cause) == (HELD, HeldBy.REVIEW, Cause.TOO_BIG_FOR_TIER)
    for word in words:
        assert word in held.note
    cards = [card for card in desired_cards(run.store.all()) if card.id.endswith(HELD_ID)]
    assert [card.kind for card in cards] == [CardKind.HELD]


def test_a_unit_of_one_group_is_held_for_a_person_without_a_planner_call_or_a_round(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch, groups=(1,), drivers=(), unsplittable="hold")
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    assert_held_for_a_person(run, "one group, 1,")
    assert run.store.get(HELD_ID).split_rounds_used == 0
    assert run.calls == 0


def test_a_driver_group_alone_over_the_earned_ceiling_is_held_for_a_person_at_once(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch, unsplittable="hold")
    run.runtime.answer = reply(
        piece(FIRST, [1, 2], "auto", 300, after=("base/1",)),
        piece(SECOND, [3], "full", 900, after=(FIRST,)),
        piece(THIRD, [4, 5], "auto", 300, after=(SECOND,)),
    )

    cli.split_held_units(run.inst, run.store)

    assert_held_for_a_person(run, "3")


def test_a_unit_that_carries_groups_of_another_change_is_held_for_a_person_with_no_round(
    tmp_path, monkeypatch
) -> None:
    run = scene(
        tmp_path, monkeypatch, joined=(Member(change="other", groups=(1,)),), unsplittable="hold"
    )
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    assert_held_for_a_person(run, "another change")
    assert run.store.get(HELD_ID).split_rounds_used == 0
    assert run.calls == 0


def test_a_unit_with_a_started_dependent_is_held_for_a_person_naming_it_with_no_round(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch, unsplittable="hold")
    run.store.set_state(DEPENDENT, IN_REVIEW, branch=f"spec/{DEPENDENT}", pr=18)
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    assert_held_for_a_person(run, DEPENDENT)
    assert run.store.get(HELD_ID).split_rounds_used == 0
    assert run.calls == 0
