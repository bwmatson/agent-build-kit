"""The node-npm profile runs chosen tests again by identifier: a file path, optionally
followed by `::` and a name, given as Vitest path filters in the run's directory
(spec: node-npm-lint-and-test)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit import profiles
from agent_build_kit.pipeline.red_check import REPORT_MARK
from tests.node_workspace import manifest, touch, workspace

MARKER = "local_stack"
A_ONE = "packages/a/src/one.test.ts"
A_TWO = "packages/a/src/two.test.ts"
A_OTHER = "packages/a/src/other.test.ts"
B_ONE = "packages/b/src/one.test.ts"
A_LIVE = "packages/a/src/live.local_stack.test.ts"
SCRIPT = 2
DIRECTORY = 4
FILTERS = 5


@pytest.fixture
def profile():
    return profiles.get("node-npm")


@pytest.fixture
def members(tmp_path: Path) -> Path:
    workspace(tmp_path, ["packages/a", "packages/b"])
    touch(tmp_path, A_ONE, A_TWO, A_OTHER, B_ONE, A_LIVE)
    return tmp_path


def member_run(profile, root: Path, member: str) -> list[str]:
    return next(
        c for c in profile.test_commands_all(root, root_extras=[]) if c[DIRECTORY] == member
    )


def e2e_run(profile, root: Path, member: str) -> list[str]:
    return next(c for c in profile.e2e_commands(root, marker=MARKER) if c[DIRECTORY] == member)


def test_a_members_run_is_narrowed_to_its_own_files_and_still_prints_the_report(
    profile, members: Path
) -> None:
    run = member_run(profile, members, "packages/a")

    again = profile.repeat_command(run, [A_ONE, A_TWO, B_ONE])

    assert again is not None
    assert again[:2] == ["sh", "-c"]
    assert again[DIRECTORY] == "packages/a"
    assert sorted(again[FILTERS:]) == ["src/one.test.ts", "src/two.test.ts"]
    assert REPORT_MARK in again[SCRIPT]


def test_a_name_after_the_file_is_ignored(profile, members: Path) -> None:
    run = member_run(profile, members, "packages/a")

    again = profile.repeat_command(run, [f"{A_ONE}::a test name"])

    assert again is not None
    assert again[FILTERS:] == ["src/one.test.ts"]


def test_identifiers_that_all_lie_under_another_member_give_none(profile, members: Path) -> None:
    run = member_run(profile, members, "packages/a")

    assert profile.repeat_command(run, [B_ONE, f"{B_ONE}::name"]) is None


def test_a_run_that_carries_filters_is_narrowed_to_the_chosen_files_that_match_them(
    profile, members: Path
) -> None:
    run = e2e_run(profile, members, "packages/a")

    again = profile.repeat_command(run, [A_LIVE, A_ONE])

    assert again is not None
    assert again[DIRECTORY] == "packages/a"
    assert again[FILTERS:] == ["src/live.local_stack.test.ts"]
    assert REPORT_MARK in again[SCRIPT]


def test_an_e2e_run_with_only_an_ordinary_file_chosen_gives_none(profile, members: Path) -> None:
    run = e2e_run(profile, members, "packages/a")

    assert profile.repeat_command(run, [A_ONE]) is None


def test_a_project_that_is_not_a_workspace_repeats_against_its_own_root(
    profile, tmp_path: Path
) -> None:
    manifest(tmp_path, "solo")
    touch(tmp_path, "src/one.test.ts", "src/two.test.ts")
    (run,) = profile.test_commands_all(tmp_path, root_extras=[])

    again = profile.repeat_command(run, ["src/one.test.ts::a name"])

    assert again is not None
    assert again[DIRECTORY] in {".", "./"}
    assert again[FILTERS:] == ["src/one.test.ts"]
    assert REPORT_MARK in again[SCRIPT]
