"""`prepare` moves a branch with no commits of its own onto the current base (spec:
prepare-base), keeping the unit's uncommitted work, and stops the unit when the move would
overwrite some of it.

The worktree is a real git repository and the move is the real one; the agent is the builder
and reviewer fakes of the graph tests.
"""

from __future__ import annotations

from pathlib import Path

from tests.empty_branch_support import BRANCH, advance, empty_branch, head, moves
from tests.factories import git
from tests.graph_driver import tick

PREDECESSOR = "spec/add-marker/0"


def test_a_branch_with_no_commits_is_fast_forwarded_to_the_base_tip_and_says_so(
    tmp_path: Path,
) -> None:
    recorder, overrides, repo = empty_branch(tmp_path)
    old = head(repo)
    new = advance(repo)

    tick(tmp_path, recorder, **overrides)

    assert head(repo) == new
    [line] = moves(recorder)
    assert old[:7] in line and new[:7] in line and line.endswith("(main)")


def test_a_branch_already_on_the_base_is_left_alone_and_logs_nothing(tmp_path: Path) -> None:
    recorder, overrides, repo = empty_branch(tmp_path)
    new = advance(repo)
    tick(tmp_path, recorder, **overrides)
    assert head(repo) == new, "the first run moved it"
    recorder.logged.clear()

    tick(tmp_path, recorder, **overrides)

    assert head(repo) == new
    assert moves(recorder) == []


def test_staged_and_unstaged_changes_of_the_unit_are_carried_along(tmp_path: Path) -> None:
    recorder, overrides, repo = empty_branch(tmp_path)
    new = advance(repo)
    (repo / "own.txt").write_text("mine\n")
    git(repo, "add", "own.txt")
    (repo / "base.txt").write_text("changed\n")

    tick(tmp_path, recorder, **overrides)

    assert head(repo) == new
    assert git(repo, "diff", "--cached", "--name-only").split() == ["own.txt"]
    assert git(repo, "diff", "--name-only").split() == ["base.txt"]
    assert (repo / "own.txt").read_text() == "mine\n"
    assert (repo / "base.txt").read_text() == "changed\n"


def test_a_move_that_would_overwrite_an_uncommitted_file_stops_the_unit_and_moves_nothing(
    tmp_path: Path,
) -> None:
    recorder, overrides, repo = empty_branch(tmp_path)
    old = head(repo)
    advance(repo, "clash.txt")
    (repo / "clash.txt").write_text("the unit's own\n")

    tick(tmp_path, recorder, **overrides)

    assert head(repo) == old
    assert (repo / "clash.txt").read_text() == "the unit's own\n"
    feedback = recorder.store.get("add-marker/1").feedback
    assert "clash.txt" in feedback and "old base" in feedback
    assert not [event for event in recorder.events if event.startswith("claude")], (
        "nothing was built on the old base"
    )
    assert moves(recorder) == []


def test_a_stacked_unit_whose_parent_merged_moves_onto_the_default_branch(
    tmp_path: Path,
) -> None:
    recorder, overrides, repo = empty_branch(tmp_path)
    git(repo, "branch", PREDECESSOR, "main")
    advance(repo, "pred.txt", on=PREDECESSOR, ref=f"refs/heads/{PREDECESSOR}")
    tick(tmp_path, recorder, base=PREDECESSOR, **overrides)
    assert head(repo) == git(repo, "rev-parse", PREDECESSOR).strip()
    # the parent merged: the trunk holds its work and more, and its branch is gone
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--ff-only", PREDECESSOR)
    git(repo, "branch", "-D", PREDECESSOR)
    git(repo, "checkout", "-q", BRANCH)
    new = advance(repo, "later.txt")
    recorder.logged.clear()

    tick(tmp_path, recorder, base="main", **overrides)

    assert head(repo) == new
    [line] = moves(recorder)
    assert line.endswith("(main)")
