"""The guarded check of a unit's branch: the commits when it is there, and when it is not a
failure that opens with cause hints and holds what the scratch installation knows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.pause import PAUSE_MARKER
from agent_build_kit.pipeline.wait_log import DECISIONS_NAME, ENDED
from tests.scratch_fakes import HandScratch, commits_on, hand_scratch
from tests.scratch_tick import TickResult, commits_on_unit_branch
from tests.usage_condition import write_pause

BRANCH = "spec/feature/1"
EXIT = 37


def tick_that_built_nothing() -> TickResult:
    return TickResult(
        returncode=EXIT,
        lines=((1.0, "nothing ready to build"),),
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
        ("2026-01-01T00:00:00+00:00", "feature/1", "backoff", ["older/1"]),
        ("2026-01-01T00:01:00+00:00", "feature/1", "blocked", ["parent/1"]),
        ("2026-01-01T00:02:00+00:00", "closed/1", "lease", []),
        ("2026-01-01T00:03:00+00:00", "closed/1", ENDED, []),
    ]
    (scratch.state / DECISIONS_NAME).write_text(
        "".join(
            json.dumps({"at": at, "unit": unit, "reason": reason, "waits_on": on, "tick": "t"})
            + "\n"
            for at, unit, reason, on in records
        )
    )
    logs = scratch.state / "unit-logs"
    logs.mkdir()
    (logs / "feature-01-run.log").write_text(
        "".join(f"run log line {number}\n" for number in range(1, 41))
    )
    write_pause(scratch.state, "wall of rate limit", kind="network")


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
    assert "feature/1: blocked, waits on parent/1" in message.splitlines()[0]
    reasons = message.split("--- wait reasons ---")[1].split("--- run log ---")[0]
    assert "blocked, waits on parent/1" in reasons
    assert "older/1" not in reasons and "backoff" not in reasons
    assert "closed/1" not in reasons
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
    (scratch.state / PAUSE_MARKER).unlink()
    (scratch.state / PAUSE_MARKER).mkdir()

    message = failure_of(scratch, tick_that_built_nothing())

    named = [line for line in message.splitlines() if "paused.json" in line]
    assert len(named) == 1 and "IsADirectoryError" in named[0]
    assert "nothing ready to build" in message
    assert "blocked, waits on parent/1" in message
    assert "run log line 40" in message


def test_a_readable_pause_marker_whose_reason_says_unavailable_is_present(tmp_path: Path) -> None:
    scratch = hand_scratch(tmp_path)
    (scratch.state / PAUSE_MARKER).write_text(
        json.dumps({"reason": "rate limited during host-unavailable-retry/1"})
    )

    message = failure_of(scratch, tick_that_built_nothing())

    assert "pause marker present" in message.splitlines()[0]
