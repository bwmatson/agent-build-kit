"""A pair that does not apply cleanly ends the reuse at its group: what was picked stays, the
failed pick is aborted, and the agent builds that group (spec: split-planning)."""

from __future__ import annotations

from pathlib import Path

from tests.factories import git
from tests.graph.branch_fakes import agent_calls, subjects
from tests.graph.piece_fakes import pairs, piece_built

# The third group's tests change a file the second group's pair made, which a piece of the first
# and third groups does not have, so that pick cannot apply.
CONFLICTING = {2: {"shared.txt": "a\n"}, 4: {"shared.txt": "b\n"}}


def built(tmp_path: Path) -> tuple[list[str], Path, list[str]]:
    recorder, _, repo = piece_built(
        tmp_path, old=pairs(1, 2, 3), piece_groups=(1, 3), files=CONFLICTING
    )
    return subjects(repo), repo, recorder.events


def test_the_pair_that_applied_stays_and_the_agent_builds_the_conflicting_group(
    tmp_path: Path,
) -> None:
    on_branch, _, events = built(tmp_path)

    assert on_branch[:2] == pairs(1), "the first pair was picked"
    assert on_branch[2:] == pairs(3), "and the third group is what the agent wrote"
    assert agent_calls(events)[:2] == ["claude:tests", "claude:impl"], events


def test_the_conflicting_pick_is_aborted_and_the_tree_is_clean(tmp_path: Path) -> None:
    _, repo, _ = built(tmp_path)

    assert git(repo, "status", "--porcelain").strip() == ""
    assert not (repo / ".git" / "CHERRY_PICK_HEAD").exists()
