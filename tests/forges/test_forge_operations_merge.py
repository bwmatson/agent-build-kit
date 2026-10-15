"""The merge operation's declaration in the operation table (spec: forge-merge)."""

from __future__ import annotations

from agent_build_kit.forges.operations import OPERATIONS


def test_the_merge_is_a_create_landing_on_the_commit_a_merged_pull_request_produced() -> None:
    spec = OPERATIONS["merge_pr"]

    assert spec.kind == "create"
    assert spec.lands == "merge_commit"
    assert not spec.contains


def test_the_commit_read_is_a_read() -> None:
    assert OPERATIONS["merge_commit"].kind == "read"
