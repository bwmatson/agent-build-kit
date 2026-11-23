"""A gate's result is a held-split entry with source `gate`, written, renewed and lifted by the
evaluation (spec: split-gate-usage)."""

from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

from agent_build_kit.pipeline.e2e_holds import (
    HELD_FILE,
    ORIGIN_CONFIGURATION,
    SOURCE_COMMAND,
    SOURCE_GATE,
    remove_hold,
    write_hold,
)
from tests.gate_hold_support import (
    COMMAND_GATE,
    END_OF_MONTH,
    LATER,
    NOW,
    PROVIDER_GATE,
    command_exiting,
    evaluate,
    gated,
    held,
    holds,
    spent,
)
from tests.parked_split_support import installation


def test_a_provider_over_its_threshold_gets_a_gate_entry_naming_the_figures(
    tmp_path: Path,
) -> None:
    inst = gated(tmp_path)

    evaluate(inst, read=spent(87))

    entry = held(inst)
    assert entry is not None
    assert entry.source == SOURCE_GATE
    assert entry.until == END_OF_MONTH
    assert entry.since == NOW
    for figure in ("modal", "87", "200", "70"):
        assert figure in entry.reason


def test_a_command_over_its_threshold_gets_a_gate_entry_one_cache_time_long(
    tmp_path: Path,
) -> None:
    inst = gated(tmp_path, COMMAND_GATE)

    evaluate(inst, run=command_exiting(3, "quota spent\n"))

    entry = held(inst)
    assert entry is not None
    assert entry.source == SOURCE_GATE
    assert entry.reason == "quota spent"
    assert entry.until == NOW + timedelta(minutes=15)


def test_a_reading_with_room_removes_the_entry_and_selection_includes_the_split_again(
    tmp_path: Path,
) -> None:
    inst = gated(tmp_path)
    evaluate(inst, read=spent(87))
    assert "acp" in holds(inst).held

    actions = evaluate(inst, now=LATER, read=spent(40))

    assert [(a.split, a.action) for a in actions] == [("acp", "lift")]
    assert "acp" not in holds(inst, now=LATER).held


def test_a_standing_entry_is_renewed_in_place_and_not_duplicated(tmp_path: Path) -> None:
    inst = gated(tmp_path)
    evaluate(inst, read=spent(87))

    actions = evaluate(inst, now=LATER, read=spent(88))

    assert [(a.split, a.action) for a in actions] == [("acp", "renew")]
    assert list(holds(inst, now=LATER).held) == ["acp"]
    entry = held(inst, now=LATER)
    assert entry is not None
    assert "88" in entry.reason
    assert entry.until == END_OF_MONTH
    assert (inst.state_dir / HELD_FILE).read_text().count('"acp"') == 1


def test_a_hand_set_hold_is_not_replaced_or_removed_by_a_reading_either_way(
    tmp_path: Path,
) -> None:
    inst = gated(tmp_path)
    write_hold(
        inst.state_dir, "acp", reason="by hand", source=SOURCE_COMMAND, by="someone", now=NOW
    )

    for moment, percent in ((NOW, 10), (LATER, 95)):
        evaluate(inst, now=moment, read=spent(percent))
        entry = held(inst, now=moment)
        assert entry is not None
        assert (entry.source, entry.reason, entry.by) == (SOURCE_COMMAND, "by hand", "someone")
        assert entry.until is None


def test_a_hold_true_split_gets_no_gate_entry_and_stays_held(tmp_path: Path) -> None:
    inst = installation(tmp_path, acp=True, gate=COMMAND_GATE)

    for moment, code in ((NOW, 3), (LATER, 0)):
        evaluate(inst, now=moment, run=command_exiting(code, "quota spent"))
        entry = held(inst, now=moment)
        assert entry is not None
        assert entry.origins == (ORIGIN_CONFIGURATION,)
        assert entry.source is None


def test_a_hold_false_split_is_not_held_whatever_the_gate_writes(tmp_path: Path) -> None:
    inst = installation(tmp_path, acp=False, gate=COMMAND_GATE)

    evaluate(inst, run=command_exiting(3, "quota spent"))

    assert held(inst) is None


def test_a_hand_hold_over_a_gate_entry_replaces_it_and_the_gate_then_leaves_it(
    tmp_path: Path,
) -> None:
    inst = gated(tmp_path)
    evaluate(inst, read=spent(87))
    write_hold(
        inst.state_dir, "acp", reason="by hand", source=SOURCE_COMMAND, by="someone", now=NOW
    )

    evaluate(inst, now=LATER, read=spent(40))

    entry = held(inst, now=LATER)
    assert entry is not None
    assert (entry.source, entry.reason) == (SOURCE_COMMAND, "by hand")


def test_a_gate_hold_released_by_hand_is_written_again_after_the_cache_time(
    tmp_path: Path,
) -> None:
    inst = gated(tmp_path)
    evaluate(inst, read=spent(87))
    assert remove_hold(inst.state_dir, "acp")
    assert held(inst) is None
    after_cache = NOW + timedelta(minutes=16)

    evaluate(inst, now=after_cache, read=spent(87))

    entry = held(inst, now=after_cache)
    assert entry is not None
    assert entry.source == SOURCE_GATE


def test_a_hand_hold_on_a_hold_false_split_is_not_replaced_by_the_gate(tmp_path: Path) -> None:
    inst = installation(tmp_path, acp=False, gate=COMMAND_GATE)
    write_hold(
        inst.state_dir, "acp", reason="by hand", source=SOURCE_COMMAND, by="someone", now=NOW
    )

    evaluate(inst, run=command_exiting(3, "quota spent"))

    entries = json.loads((inst.state_dir / HELD_FILE).read_text())
    assert (entries["acp"]["source"], entries["acp"]["reason"], entries["acp"]["by"]) == (
        SOURCE_COMMAND,
        "by hand",
        "someone",
    )


def test_a_gate_entry_on_a_hold_false_split_is_lifted_by_a_reading_with_room(
    tmp_path: Path,
) -> None:
    inst = installation(tmp_path, acp=False, gate=PROVIDER_GATE)
    evaluate(inst, read=spent(87))
    assert "acp" in json.loads((inst.state_dir / HELD_FILE).read_text())

    actions = evaluate(inst, now=LATER, read=spent(40))

    assert [(a.split, a.action) for a in actions] == [("acp", "lift")]
    assert "acp" not in json.loads((inst.state_dir / HELD_FILE).read_text())
