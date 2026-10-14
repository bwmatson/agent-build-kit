"""The node-npm profile runs the tests of the workspace members a change touched, each in
its own directory (spec: node-npm-workspaces)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from tests.node_workspace import workspace


@pytest.fixture
def profile():
    return profiles.get("node-npm")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    workspace(tmp_path, ["packages/a", "packages/b"])
    return tmp_path


def words(command: list[str]) -> str:
    return " ".join(command)


def test_a_change_in_one_member_runs_one_command_in_that_members_directory(profile, repo) -> None:
    (command,) = profile.test_commands(repo, ["packages/a/src/x.ts"], root_extras=[])

    assert "packages/a" in words(command)
    assert "packages/b" not in words(command)


def test_a_change_to_the_root_manifest_runs_every_member(profile, repo) -> None:
    commands = profile.test_commands(repo, ["package.json"], root_extras=[])

    assert len(commands) == 2
    assert sorted("packages/a" in words(c) for c in commands) == [False, True]
    assert sorted("packages/b" in words(c) for c in commands) == [False, True]


def test_a_changed_test_file_at_the_workspace_root_runs_beside_the_members(profile, repo) -> None:
    commands = profile.test_commands(repo, ["tests/e2e.test.ts"], root_extras=[])

    assert len(commands) == 3
    (root,) = [c for c in commands if "tests/e2e.test.ts" in c]
    assert root[4:] == ["./", "tests/e2e.test.ts"]
