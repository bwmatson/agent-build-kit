"""An unreadable gate is unknown, never a pass, and `on_unknown` says whether it holds (spec:
split-gate-usage)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

from agent_build_kit.pipeline.e2e_holds import SOURCE_GATE
from tests.gate_hold_support import (
    COMMAND_GATE,
    END_OF_MONTH,
    LATER,
    NOW,
    PROVIDER_GATE,
    command_missing,
    evaluate,
    gated,
    held,
    spent,
    unreadable,
)

RETRY = timedelta(minutes=5)
HOLDING = {**PROVIDER_GATE, "on_unknown": "hold"}


def test_under_allow_an_unknown_result_writes_nothing_and_lifts_nothing(tmp_path: Path) -> None:
    inst = gated(tmp_path)

    actions = evaluate(inst, read=unreadable)

    assert actions == []
    assert held(inst) is None


def test_under_allow_a_standing_gate_hold_stands_through_an_unknown_result(
    tmp_path: Path,
) -> None:
    inst = gated(tmp_path)
    evaluate(inst, read=spent(87))
    before = held(inst)
    assert before is not None

    actions = evaluate(inst, now=LATER, read=unreadable)

    assert all(action.action != "lift" for action in actions)
    after = held(inst, now=LATER)
    assert after is not None
    assert (after.reason, after.until) == (before.reason, END_OF_MONTH)


def test_under_hold_an_unknown_result_writes_an_entry_saying_so(tmp_path: Path) -> None:
    inst = gated(tmp_path, HOLDING)

    evaluate(inst, read=unreadable)

    entry = held(inst)
    assert entry is not None
    assert entry.source == SOURCE_GATE
    assert "unknown" in entry.reason
    assert entry.until == NOW + RETRY


def test_under_hold_each_unknown_round_renews_the_entry(tmp_path: Path) -> None:
    inst = gated(tmp_path, HOLDING)
    evaluate(inst, read=unreadable)
    later = NOW + timedelta(minutes=6)

    actions = evaluate(inst, now=later, read=unreadable)

    assert [(a.split, a.action) for a in actions] == [("acp", "renew")]
    entry = held(inst, now=later)
    assert entry is not None
    assert entry.until == later + RETRY


def test_under_hold_the_first_good_reading_replaces_the_unknown_entry(tmp_path: Path) -> None:
    inst = gated(tmp_path, HOLDING)
    evaluate(inst, read=unreadable)

    evaluate(inst, now=LATER, read=spent(87))

    entry = held(inst, now=LATER)
    assert entry is not None
    assert "unknown" not in entry.reason
    assert entry.until == END_OF_MONTH


def test_under_hold_a_good_reading_with_room_lifts_the_unknown_entry(tmp_path: Path) -> None:
    inst = gated(tmp_path, HOLDING)
    evaluate(inst, read=unreadable)

    evaluate(inst, now=LATER, read=spent(40))

    assert held(inst, now=LATER) is None


def test_a_command_that_cannot_run_is_unknown_and_holds_only_under_hold(
    tmp_path: Path,
) -> None:
    allowing = gated(tmp_path / "allow", COMMAND_GATE)
    holding = gated(tmp_path / "hold", {**COMMAND_GATE, "on_unknown": "hold"})

    evaluate(allowing, run=command_missing)
    evaluate(holding, run=command_missing)

    assert held(allowing) is None
    entry = held(holding)
    assert entry is not None
    assert "unknown" in entry.reason
