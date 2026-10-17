"""The dump's caps: each item, one dump, and the session."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.pipeline.wait_log import ENDED
from tests import scratch_dump
from tests.scratch_dump_support import (
    TICK_LINE,
    add_decisions,
    add_heads,
    add_ledger,
    add_pause,
    add_run_log,
    add_units,
    bare_scratch,
    filled_scratch,
    run_children,
    sections,
    stand_in_tick,
)


def lines_with(text: str, token: str) -> list[str]:
    return [line for line in text.splitlines() if token in line]


def test_a_tick_output_of_a_hundred_thousand_characters_is_cut_to_its_last_six_thousand(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = bare_scratch(tmp_path)
    output = [f"TICKLINE-{number:04d} " + "t" * 88 for number in range(1000)]
    stand_in_tick(scratch, monkeypatch, output)

    text = scratch_dump.scratch_state(scratch)

    shown = lines_with(text, "TICKLINE-")
    assert "TICKLINE-0999" in text and "TICKLINE-0000" not in text
    assert sum(len(line) + 1 for line in shown) <= 6000 + 100
    assert len(shown) >= 55


def test_forty_units_give_twenty_unit_lines_and_twenty_reason_lines(
    tmp_path: Path,
) -> None:
    scratch = bare_scratch(tmp_path)
    add_units(scratch, [f"s{number:02d}/1" for number in range(40)])
    add_decisions(
        scratch,
        [
            (f"r{number:02d}/1", "blocked", [f"WAITTOKEN-{number:02d}-" + "w" * 400])
            for number in range(40)
        ]
        + [(f"filler{number}/1", ENDED, []) for number in range(15)],
    )

    text = scratch_dump.scratch_state(scratch)

    assert len(re.findall(r"\bs\d\d/1\b", text)) == 20
    reasons = lines_with(text, "WAITTOKEN")
    assert len(reasons) == 20
    assert all(len(line.strip()) <= 200 for line in reasons)


def test_a_pause_marker_of_five_thousand_characters_is_cut_to_a_thousand(
    tmp_path: Path,
) -> None:
    scratch = bare_scratch(tmp_path)
    add_pause(scratch, "p" * 5000)

    text = scratch_dump.scratch_state(scratch)

    longest = max(len(run) for run in re.findall(r"p+", text))
    assert 900 <= longest <= 1000


def test_a_hundred_branches_give_thirty_lines(tmp_path: Path) -> None:
    scratch = bare_scratch(tmp_path)
    add_heads(scratch, [f"bulk-{number:03d}" for number in range(100)])

    text = scratch_dump.scratch_state(scratch)

    assert len(lines_with(text, "refs/heads/bulk-")) == 30


def test_each_log_tail_gives_fifteen_lines_of_at_most_three_hundred_characters(
    tmp_path: Path,
) -> None:
    scratch = bare_scratch(tmp_path)
    add_run_log(scratch, [f"LOGLINE-{number:02d} " + "z" * 600 for number in range(40)])
    add_ledger(scratch, [f"LEDGERROW-{number:02d}-" + "x" * 500 for number in range(40)])

    text = scratch_dump.scratch_state(scratch)

    for token in ("LOGLINE-", "LEDGERROW-"):
        shown = lines_with(text, token)
        assert len(shown) == 15, token
        assert all(len(line.strip()) <= 300 for line in shown), token
        assert f"{token}39" in text and f"{token}24" not in text


def test_one_dump_is_at_most_twenty_thousand_four_hundred_and_eighty_characters(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    scratch = filled_scratch(tmp_path)
    add_units(scratch, [f"s{number:02d}/1" for number in range(40)])
    add_decisions(
        scratch,
        [(f"r{number:02d}/1", "blocked", ["w" * 400]) for number in range(40)],
    )
    add_pause(scratch, "p" * 5000)
    add_heads(scratch, [f"bulk-{number:03d}" for number in range(100)])
    add_run_log(scratch, ["z" * 600 for _ in range(40)])
    add_ledger(scratch, ["x" * 500 for _ in range(40)])
    stand_in_tick(scratch, monkeypatch, ["t" * 100 for _ in range(1000)])

    text = scratch_dump.scratch_state(scratch)

    assert scratch_dump.DUMP_CHARS == 20480
    assert len(text) <= 20480
    assert TICK_LINE not in text and "tttt" in text


def test_a_dump_that_would_pass_the_session_budget_is_left_out_and_every_one_after_it(
    pytester: pytest.Pytester, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = filled_scratch(tmp_path)
    stand_in_tick(probe, monkeypatch)
    size = len(scratch_dump.scratch_state(probe))
    # The first dump fits; the second would take the session past this.
    budget = size + size // 2
    monkeypatch.setattr(scratch_dump, "SESSION_CHARS", budget)
    body = """\

@pytest.mark.local_stack
def test_one(tmp_path, monkeypatch):
    ticked_scratch(tmp_path, monkeypatch)
    pytest.fail("one")


@pytest.mark.local_stack
def test_two(tmp_path, monkeypatch):
    ticked_scratch(tmp_path, monkeypatch)
    pytest.fail("two")


@pytest.mark.local_stack
def test_tre(tmp_path, monkeypatch):
    ticked_scratch(tmp_path, monkeypatch)
    pytest.fail("tre")
"""
    result = run_children(pytester, body)

    first, second, third = sections(result.outlines)
    assert first[0].startswith("cause hints:")
    for left_out in (second, third):
        lines = [line for line in left_out if line.strip()]
        assert len(lines) == 1 and "left out" in lines[0]
    printed = sum(len("\n".join(section).strip()) for section in (first, second, third))
    assert printed <= budget
