"""After a published planning pull request lands, the sync fast-forwards over the files it
published, removing or restoring one only when it is identical to the incoming content."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.planning_sync import SyncOutcome
from tests.factories import git
from tests.pipeline.test_planning_sync import sync
from tests.planning_worktree_support import in_repo, publish_elsewhere

LOG = "runs/track-health.md"
PUBLISHED = "# Run log\n\n**Status:** OK\n"


def test_an_untracked_published_file_identical_to_the_landed_one_is_removed_and_the_sync_moves(
    tmp_path: Path,
) -> None:
    setup = in_repo(tmp_path)
    (setup.worktree / LOG).write_text(PUBLISHED)
    tip = publish_elsewhere(setup, {LOG: PUBLISHED}, "landed")

    result, _ = sync(setup)

    assert result.outcome == SyncOutcome.SYNCED
    assert git(setup.worktree, "rev-parse", "HEAD") == tip
    assert (setup.worktree / LOG).read_text() == PUBLISHED
    assert git(setup.worktree, "status", "--porcelain") == ""


def test_a_modified_file_identical_to_the_landed_one_is_restored_and_the_sync_moves(
    tmp_path: Path,
) -> None:
    setup = in_repo(tmp_path)
    (setup.worktree / "README.md").write_text("published content\n")
    tip = publish_elsewhere(setup, {"README.md": "published content\n"}, "landed")

    result, _ = sync(setup)

    assert result.outcome == SyncOutcome.SYNCED
    assert git(setup.worktree, "rev-parse", "HEAD") == tip
    assert (setup.worktree / "README.md").read_text() == "published content\n"


def test_an_untracked_file_that_differs_from_the_landed_one_stops_the_sync_and_is_kept(
    tmp_path: Path,
) -> None:
    setup = in_repo(tmp_path)
    before = git(setup.worktree, "rev-parse", "HEAD")
    (setup.worktree / LOG).write_text("my own notes\n")
    publish_elsewhere(setup, {LOG: PUBLISHED}, "landed")

    result, _ = sync(setup)

    assert result.outcome == SyncOutcome.STOPPED
    assert result.reason
    assert git(setup.worktree, "rev-parse", "HEAD") == before
    assert (setup.worktree / LOG).read_text() == "my own notes\n"


def test_a_modified_file_that_differs_from_the_landed_one_stops_the_sync_and_is_kept(
    tmp_path: Path,
) -> None:
    setup = in_repo(tmp_path)
    before = git(setup.worktree, "rev-parse", "HEAD")
    (setup.worktree / "README.md").write_text("my edit\n")
    publish_elsewhere(setup, {"README.md": "published content\n"}, "landed")

    result, _ = sync(setup)

    assert result.outcome == SyncOutcome.STOPPED
    assert result.reason
    assert git(setup.worktree, "rev-parse", "HEAD") == before
    assert (setup.worktree / "README.md").read_text() == "my edit\n"
