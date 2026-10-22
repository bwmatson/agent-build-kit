"""A piece whose groups were built per group on the superseded branch takes their pairs by
cherry-pick when its run is prepared, and goes on from the branch (spec: split-planning)."""

from __future__ import annotations

from pathlib import Path

from tests.factories import git
from tests.graph.branch_fakes import agent_calls, subjects
from tests.graph.piece_fakes import KEPT, pairs, piece_built


def test_a_piece_for_the_third_group_has_that_pair_and_no_agent_writes_it(tmp_path: Path) -> None:
    recorder, outcome, repo = piece_built(tmp_path, old=pairs(1, 2, 3), piece_groups=(3,))

    assert subjects(repo) == pairs(3)
    assert agent_calls(recorder.events) == [], "no agent is run for a group taken from the branch"
    assert not list(repo.glob("work-*.txt")), "and none writes a file"
    assert outcome.status == "open"
    assert git(repo, "log", "--format=%s", KEPT).split("\n")[:2] == ["feat: G3", "test: G3"]


def test_a_piece_for_the_first_two_groups_has_both_pairs_in_order(tmp_path: Path) -> None:
    recorder, _, repo = piece_built(tmp_path, old=pairs(1, 2, 3), piece_groups=(1, 2))

    assert subjects(repo) == pairs(1, 2)
    assert agent_calls(recorder.events) == []


def test_the_run_goes_on_from_the_branch_to_its_checks(tmp_path: Path) -> None:
    recorder, _, _ = piece_built(tmp_path, old=pairs(1, 2, 3), piece_groups=(3,))

    assert recorder.events.index("unit-test") < recorder.events.index("review")
    assert "claude:tests" not in recorder.events
    assert "claude:impl" not in recorder.events
