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


def affected(profile, repo, changed: list[str], tmp_path: Path):
    return profile.affected_test_commands(
        repo, changed, [], seed=tmp_path / "seed" / "affected", root_extras=[]
    )


def test_a_changed_source_file_selects_the_tests_that_reach_it_through_vitest_related(
    profile, repo, tmp_path: Path
) -> None:
    (command,) = affected(profile, repo, ["packages/a/src/x.ts"], tmp_path)

    assert command[4] == "packages/a"
    assert "related" in command[2]
    assert "src/x.ts" in command[5:]


def test_a_change_to_documentation_selects_no_tests(profile, repo, tmp_path: Path) -> None:
    assert affected(profile, repo, ["packages/a/README.md"], tmp_path) == []


@pytest.mark.parametrize(
    "shared",
    [
        "packages/a/vitest.config.ts",
        "packages/a/package-lock.json",
        "package-lock.json",
        "package.json",
    ],
    ids=["a member's configuration", "a member's lock file", "the root lock file", "the manifest"],
)
def test_a_change_to_a_shared_file_runs_the_whole_member_not_a_selection(
    profile, repo, tmp_path: Path, shared: str
) -> None:
    commands = affected(profile, repo, [shared, "packages/a/src/x.ts"], tmp_path)

    assert commands
    assert all("related" not in command[2] for command in commands)
    assert commands == profile.test_commands(repo, [shared], root_extras=[])


def test_a_change_to_a_setup_file_the_configuration_names_runs_the_whole_member(
    profile, repo, tmp_path: Path
) -> None:
    (repo / "packages/a/vitest.config.ts").write_text(
        'export default { test: { setupFiles: ["./test/setup.ts"] } };\n'
    )

    commands = affected(profile, repo, ["packages/a/test/setup.ts"], tmp_path)

    assert commands == profile.test_commands(repo, ["packages/a/src/x.ts"], root_extras=[])
