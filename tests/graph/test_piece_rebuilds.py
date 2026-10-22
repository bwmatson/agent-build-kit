"""A superseded branch that is not exactly a pair for each of its unit's groups, in order, is not
reused: the piece is built from scratch and the reason is said once (spec: split-planning)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.graph.branch_fakes import agent_calls, subjects
from tests.graph.piece_fakes import pairs, piece_built

REBUILT = {
    "a fix commit": [*pairs(1, 2, 3), "fix: Address review"],
    "a commit that is no pair's": [*pairs(1, 2), "test: Other", "feat: Other"],
    "a missing pair": pairs(1, 3),
    "a build from before per-group commits": [
        "test: Register the marker",
        "feat: Register the marker",
    ],
}


@pytest.mark.parametrize("old", REBUILT.values(), ids=REBUILT.keys())
def test_the_piece_is_built_from_scratch_and_the_reason_is_said_once(
    tmp_path: Path, old: list[str]
) -> None:
    recorder, _, repo = piece_built(tmp_path, old=old, piece_groups=(3,))

    assert agent_calls(recorder.events)[:2] == ["claude:tests", "claude:impl"]
    assert subjects(repo) == pairs(3), "only what the agent wrote, none of the old commits"
    said = [line for line in recorder.logged if "reuse" in line.lower()]
    assert len(said) == 1, recorder.logged
