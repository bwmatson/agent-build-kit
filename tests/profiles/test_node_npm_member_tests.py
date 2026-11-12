"""The node-npm profile runs the tests of the workspace members a change touched, each in
its own directory (spec: node-npm-workspaces)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from tests.node_workspace import manifest, workspace


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


def test_a_failed_id_outside_the_import_graph_of_the_change_is_in_the_related_run(
    profile, repo, tmp_path: Path
) -> None:
    (command,) = profile.affected_test_commands(
        repo,
        ["packages/a/src/x.ts"],
        ["packages/a/src/other.test.ts::adds", "packages/a/src/x.test.ts"],
        seed=tmp_path / "seed" / "affected",
        root_extras=[],
    )

    assert command[4] == "packages/a"
    assert command[5:] == ["src/x.ts", "src/other.test.ts", "src/x.test.ts"]


def test_a_failed_id_at_the_workspace_root_runs_again_from_the_root(
    profile, repo, tmp_path: Path
) -> None:
    commands = profile.affected_test_commands(
        repo,
        ["packages/a/src/x.ts"],
        ["tests/e2e.test.ts::adds"],
        seed=tmp_path / "seed" / "affected",
        root_extras=[],
    )

    (root,) = [c for c in commands if c[4] == "./"]
    assert "tests/e2e.test.ts" in root[5:]
    assert len(commands) == 2


def test_a_changed_data_file_in_a_member_runs_the_whole_member(
    profile, repo, tmp_path: Path
) -> None:
    commands = affected(profile, repo, ["packages/a/src/data.json"], tmp_path)

    assert commands == profile.test_commands(repo, ["packages/a/src/data.json"], root_extras=[])
    assert all("related" not in command[2] for command in commands)


def test_a_project_that_is_not_a_workspace_gets_one_related_run_in_its_own_directory(
    profile, tmp_path: Path
) -> None:
    manifest(tmp_path, "solo")

    (command,) = affected(profile, tmp_path, ["src/x.ts", "src/y.ts"], tmp_path)

    assert command[4] == "./"
    assert "related" in command[2]
    assert command[5:] == ["src/x.ts", "src/y.ts"]


def test_a_shared_change_in_a_project_that_is_not_a_workspace_is_one_whole_run(
    profile, tmp_path: Path
) -> None:
    manifest(tmp_path, "solo")

    commands = affected(profile, tmp_path, ["src/x.ts", "package.json"], tmp_path)

    assert commands == profile.test_commands(tmp_path, ["package.json"], root_extras=[])


def test_an_affected_run_lets_the_integration_files_the_default_run_excludes_through(
    profile, repo, tmp_path: Path
) -> None:
    (repo / "packages/a/vitest.config.ts").write_text(
        'export default { test: { exclude: ["**/*.integration.test.ts"] } };\n'
    )

    (command,) = affected(profile, repo, ["packages/a/src/x.ts"], tmp_path)

    assert "related" in command[2]
    assert ".integration.test" in words(command)
