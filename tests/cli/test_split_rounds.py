"""Each split attempt that succeeds or fails uses a round of its lineage and an outage uses none;
a unit with no round left is held for a person (spec: split-planning)."""

from __future__ import annotations

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause, HeldBy
from agent_build_kit.pipeline.units import HELD
from tests.cli.plan_outage_fakes import network, raises, service
from tests.split_step_support import HELD_ID, PIECES, correct, piece, reply, scene

pytestmark = pytest.mark.usefixtures("scripted_engine")

FIRST, SECOND, THIRD = PIECES


def mixed() -> str:
    """A plan that puts the driver group 3 beside group 2."""
    return reply(
        piece(FIRST, [1], "auto", 300, after=("base/1",)),
        piece(SECOND, [2, 3], "full", 300, after=(FIRST,)),
        piece(THIRD, [4, 5], "auto", 300, after=(SECOND,)),
    )


def too_large() -> str:
    """A plan whose first piece is over the ceiling of its tier."""
    return reply(
        piece(FIRST, [1, 2], "full", 900, after=("base/1",)),
        piece(SECOND, [3], "full", 300, after=(FIRST,)),
        piece(THIRD, [4, 5], "auto", 300, after=(SECOND,)),
    )


@pytest.mark.parametrize("answer", [too_large(), "I could not.", mixed()], ids=lambda a: a[:12])
def test_a_refused_plan_an_invalid_reply_and_a_plan_ignoring_the_pins_each_use_one_round(
    tmp_path, monkeypatch, answer: str
) -> None:
    run = scene(tmp_path, monkeypatch)
    run.runtime.answer = answer

    cli.split_held_units(run.inst, run.store)

    kept = run.store.get(HELD_ID)
    assert (kept.state, kept.held_by) == (HELD, HeldBy.SIZE)
    assert kept.split_rounds_used == 1
    assert kept.split_request is not None, "kept for the next tick"
    assert run.calls == 1


@pytest.mark.parametrize("error", [network(), service()], ids=["network", "service"])
def test_an_outage_uses_no_round_and_leaves_the_unit_held_by_size(
    tmp_path, monkeypatch, error: Exception
) -> None:
    run = scene(tmp_path, monkeypatch)
    run.runtime.act = raises(error)

    cli.split_held_units(run.inst, run.store)

    kept = run.store.get(HELD_ID)
    assert (kept.state, kept.held_by) == (HELD, HeldBy.SIZE)
    assert kept.split_rounds_used == 0


def test_a_lineage_with_its_rounds_used_is_held_for_a_person_without_a_planner_call(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch, used=2)
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    held = run.store.get(HELD_ID)
    assert (held.state, held.held_by, held.cause) == (HELD, HeldBy.REVIEW, Cause.TOO_BIG_FOR_TIER)
    assert "2 of 2" in held.note
    assert run.calls == 0


def test_zero_rounds_makes_no_planner_call_and_holds_the_unit_for_a_person(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch, rounds=0)
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    held = run.store.get(HELD_ID)
    assert (held.state, held.held_by, held.cause) == (HELD, HeldBy.REVIEW, Cause.TOO_BIG_FOR_TIER)
    assert "split_rounds" in held.note
    assert run.calls == 0


def test_a_piece_inherits_the_count_so_a_piece_of_a_first_split_has_one_round_left(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch)
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    assert [run.store.get(uid).split_rounds_used for uid in PIECES] == [1, 1, 1]


def test_a_failed_round_then_a_success_leaves_the_pieces_with_both_counted(
    tmp_path, monkeypatch
) -> None:
    run = scene(tmp_path, monkeypatch)
    run.runtime.answer = "I could not."
    cli.split_held_units(run.inst, run.store)
    run.runtime.answer = reply(*correct())

    cli.split_held_units(run.inst, run.store)

    assert [run.store.get(uid).split_rounds_used for uid in PIECES] == [2, 2, 2]
