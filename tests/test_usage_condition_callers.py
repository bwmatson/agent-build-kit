"""The live tests that start a scratch tick (build, graph, telemetry) all end a tick that built
nothing through the one guarded branch check, which skips on a usage condition and otherwise
fails as it did."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.scratch_fakes import hand_scratch
from tests.scratch_tick import TickResult, commits_on_unit_branch
from tests.usage_condition import write_pause

BRANCH = "spec/feature/1"
REASON = "session usage at 91% (threshold 70%, live)"
TICK = TickResult(
    returncode=0, lines=((1.0, "pausing until 12:00 — " + REASON),), started=0.5, ended=2.0
)


def test_the_branch_check_skips_a_tick_that_built_nothing_under_a_usage_pause(
    tmp_path: Path,
) -> None:
    scratch = hand_scratch(tmp_path)
    write_pause(scratch.state, REASON, kind="usage")

    with pytest.raises(pytest.skip.Exception) as raised:
        commits_on_unit_branch(scratch, BRANCH, TICK)

    assert "91%" in str(raised.value)


@pytest.mark.parametrize("kind", ["network", None])
def test_the_failure_of_a_tick_that_built_nothing_without_a_usage_pause_is_unchanged(
    tmp_path: Path, kind: str | None
) -> None:
    scratch = hand_scratch(tmp_path)
    if kind == "network":
        write_pause(scratch.state, REASON, kind=kind)

    with pytest.raises(pytest.fail.Exception) as raised:
        commits_on_unit_branch(scratch, BRANCH, TICK)

    text = str(raised.value)
    assert text.startswith("cause hints: tick exited 0; "), text
    assert "--- tick output ---" in text, text
