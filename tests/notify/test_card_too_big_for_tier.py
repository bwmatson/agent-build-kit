"""A unit held for its size and waiting for a split raises no card; held for a person it does
(spec: hold-and-split, a unit held as too big for its tier)."""

from __future__ import annotations

from agent_build_kit.notify.cards import desired_cards
from agent_build_kit.notify.provider import CardKind
from agent_build_kit.pipeline.unit_store import Cause, HeldBy
from agent_build_kit.pipeline.units import HELD
from tests.factories import stored_unit


def held(held_by: HeldBy):
    history = ({"state": HELD, "cause": Cause.TOO_BIG_FOR_TIER.value, "note": "too big"},)
    return stored_unit(state=HELD, held_by=held_by, history=history)


def test_a_unit_held_by_size_raises_no_card() -> None:
    assert desired_cards([held(HeldBy.SIZE)]) == []


def test_the_same_unit_held_for_a_person_raises_a_card() -> None:
    cards = desired_cards([held(HeldBy.REVIEW)])

    assert [card.kind for card in cards] == [CardKind.HELD]
