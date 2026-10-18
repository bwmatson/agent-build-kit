"""Asking whether a branch is held never takes the branch, so a build starting at the same
moment is not turned away by the question (spec: unit-scheduling)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.workspaces import branch_held

BRANCH = "spec/add-marker/1"


def test_asking_about_a_free_branch_leaves_nothing_on_disk_for_a_build_to_meet(
    tmp_path: Path,
) -> None:
    root = tmp_path / "locks"

    assert branch_held(BRANCH, root=root) is False

    assert not root.exists()
