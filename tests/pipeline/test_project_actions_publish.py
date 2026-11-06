"""The commit of abk.yaml is published, so a pipeline worktree never diverges from origin
(spec: project-lines).

Real git: a bare origin, the person's working copy and the detached pipeline worktree."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.planning_sync import SyncOutcome, sync_planning
from agent_build_kit.pipeline.project_actions import commit_project_file
from tests.factories import git
from tests.planning_worktree_support import in_repo, installation_at, publish_elsewhere


def test_the_commit_reaches_origin_and_the_worktree_still_syncs_after_origin_moves(
    tmp_path: Path,
) -> None:
    setup = in_repo(tmp_path, files={"abk.yaml": "repos: {}\n"})
    inst = installation_at(setup.worktree, setup.working_copy)
    (setup.worktree / "abk.yaml").write_text("repos: {edited: true}\n")
    assert setup.origin is not None

    assert commit_project_file(inst, "feature", 2, log=lambda line: None) is True

    files = git(setup.origin, "show", "--name-only", "--format=", "main").splitlines()
    assert files == ["abk.yaml"]
    assert "feature" in git(setup.origin, "log", "-1", "--format=%s", "main")
    publish_elsewhere(setup, {"notes.md": "a person's note\n"})

    synced = sync_planning(inst, lambda message: None)

    assert synced.outcome == SyncOutcome.SYNCED, synced.reason
    assert git(setup.worktree, "rev-parse", "HEAD") == git(setup.origin, "rev-parse", "main")
