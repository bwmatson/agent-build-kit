"""The guarded check of a unit's branch: the commits when it is there, and when it is not a
failure that opens with cause hints and holds what the scratch installation knows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.scratch_fakes import HandScratch, commits_on, hand_scratch
from tests.scratch_tick import TickResult, commits_on_unit_branch

BRANCH = "spec/feature/1"
EXIT = 37


def tick_that_built_nothing() -> TickResult:
    return TickResult(
        returncode=EXIT,
        lines=((1.0, "nothing ready to build"), (2.0, "  feature/1 (app): blocked")),
        started=0.5,
        ended=2.5,
    )


def failure_of(scratch: HandScratch, tick: TickResult | None) -> str:
    with pytest.raises(pytest.fail.Exception) as raised:
        commits_on_unit_branch(scratch, BRANCH, tick)
    return str(raised.value)


def fill_state(scratch: HandScratch) -> None:
    """What a tick leaves: the decision log, a run log and a pause marker."""
    records = [
        {"at": "2026-01-01T00:00:00+00:00", "unit": "feature/1", "reason": "backoff"},
        {"at": "2026-01-01T00:01:00+00:00", "unit": "feature/1", "reason": "blocked"},
    ]
    (scratch.state / "decisions.jsonl").write_text(
        "".join(
            json.dumps({**record, "waits_on": ["parent/1"], "tick": "t"}) + "\n"
            for record in records
        )
    )
    logs = scratch.state / "unit-logs"
    logs.mkdir()
    (logs / "feature-01-run.log").write_text(
        "".join(f"run log line {number}\n" for number in range(1, 41))
    )
    (scratch.state / "paused.json").write_text(
        json.dumps({"until": "2099-01-01T00:00:00+00:00", "reason": "wall of rate limit"})
    )


def test_a_branch_of_two_commits_gives_their_ids(tmp_path: Path) -> None:
    scratch = hand_scratch(tmp_path, branch=BRANCH)

    found = commits_on_unit_branch(scratch, BRANCH, tick_that_built_nothing())

    assert len(found) == 2
    assert sorted(found) == sorted(commits_on(scratch, BRANCH))


def test_a_missing_branch_fails_with_hints_first_and_then_what_the_scratch_knows(
    tmp_path: Path,
) -> None:
    scratch = hand_scratch(tmp_path)
    fill_state(scratch)

    message = failure_of(scratch, tick_that_built_nothing())

    assert message.splitlines()[0].startswith("cause hints:")
    assert str(EXIT) in message
    assert "nothing ready to build" in message
    assert "feature/1" in message and "blocked" in message and "parent/1" in message
    assert "run log line 40" in message
    assert "wall of rate limit" in message
    assert f"remote reflog of {BRANCH}" in message


def test_a_missing_pause_marker_is_shown_as_absent(tmp_path: Path) -> None:
    scratch = hand_scratch(tmp_path)

    message = failure_of(scratch, tick_that_built_nothing())

    assert "absent" in message


def test_a_missing_branch_with_no_remembered_tick_says_no_tick_was_run(tmp_path: Path) -> None:
    scratch = hand_scratch(tmp_path)

    message = failure_of(scratch, None)

    assert message.splitlines()[0].startswith("cause hints:")
    assert "no tick was run" in message


def test_a_source_that_cannot_be_read_is_named_in_one_line_and_hides_nothing_else(
    tmp_path: Path,
) -> None:
    scratch = hand_scratch(tmp_path)
    fill_state(scratch)
    (scratch.state / "paused.json").unlink()
    (scratch.state / "paused.json").mkdir()

    message = failure_of(scratch, tick_that_built_nothing())

    named = [line for line in message.splitlines() if "paused.json" in line]
    assert len(named) == 1 and "IsADirectoryError" in named[0]
    assert "nothing ready to build" in message
    assert "blocked" in message
    assert "run log line 40" in message
