"""`abk doctor` over the `.planning` link and the state location (spec: planning-state-view)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import Check
from agent_build_kit.pipeline.planning_view import LINK_NAME
from tests.cli.in_repo_doctor import (
    PROTECTED,
    STATE_IGNORES,
    checks_of,
    host_says,
    named,
    separate,
    with_pipeline_worktree,
)
from tests.cli.public_content_repo import planning
from tests.factories import init_repo

VIEW = "planning view"
LOCATION = "state location"


def in_repo_with_state(root: Path, state: Path) -> Path:
    """The `abk.yaml` of a repository that lists itself as its one repo, keeping its state in
    `state`."""
    host_says(PROTECTED)
    return planning(root, ignore=STATE_IGNORES, publish="branch", state_dir=str(state))


def link_to(root: Path, target: Path) -> None:
    (root / LINK_NAME).symlink_to(target)


def view_of(config: Path) -> Check:
    [found] = named(checks_of(config), VIEW)
    return found


def test_a_right_link_is_ok_in_the_working_copy_and_from_the_pipeline_worktree(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    config = in_repo_with_state(tmp_path / "app", state)
    link_to(config.parent, state)
    worktree = with_pipeline_worktree(config)

    assert view_of(config).status == "ok"
    assert view_of(worktree / "abk.yaml").status == "ok"


@pytest.mark.parametrize(
    ("problem", "said"),
    [("missing", "missing"), ("dangling", "dangling"), ("elsewhere", "points to")],
)
def test_a_link_that_is_not_right_warns_naming_init_in_both_roles(
    tmp_path: Path, problem: str, said: str
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    config = in_repo_with_state(tmp_path / "app", state)
    if problem == "dangling":
        link_to(config.parent, tmp_path / "gone")
    if problem == "elsewhere":
        other = tmp_path / "other"
        other.mkdir()
        link_to(config.parent, other)
    worktree = with_pipeline_worktree(config)

    for found in (view_of(config), view_of(worktree / "abk.yaml")):
        assert found.status == "warn"
        assert "abk init" in found.fix
        assert said in found.detail


def test_a_separate_planning_repo_has_no_planning_view_check(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    inside = in_repo_with_state(tmp_path / "app", state)
    link_to(inside.parent, state)
    code = init_repo(tmp_path / "code")
    apart = separate(tmp_path / "plan", code)

    assert [c.status for c in named(checks_of(inside), VIEW)] == ["ok"]
    assert named(checks_of(apart), VIEW) == []


def test_a_state_directory_under_the_repository_warns_naming_the_resolved_path(
    tmp_path: Path,
) -> None:
    root = tmp_path / "app"
    state = root / "state"
    config = in_repo_with_state(root, state)

    [found] = named(checks_of(config), LOCATION)

    assert found.status == "warn"
    assert str(state.resolve()) in found.detail


def test_a_state_directory_under_the_git_directory_warns(tmp_path: Path) -> None:
    root = tmp_path / "app"
    state = root / ".git" / "abk-state"
    config = in_repo_with_state(root, state)

    [found] = named(checks_of(config), LOCATION)

    assert found.status == "warn"
    assert str(state.resolve()) in found.detail


def test_a_state_link_that_leads_into_the_repository_warns_naming_where_it_leads(
    tmp_path: Path,
) -> None:
    root = tmp_path / "app"
    inside = root / "inside"
    inside.mkdir(parents=True)
    state = tmp_path / "state-link"
    state.symlink_to(inside)
    config = in_repo_with_state(root, state)

    [found] = named(checks_of(config), LOCATION)

    assert found.status == "warn"
    assert str(inside.resolve()) in found.detail


def test_a_state_directory_outside_the_repository_and_a_separate_repo_give_no_warning(
    tmp_path: Path,
) -> None:
    state = tmp_path / "state"
    state.mkdir()
    outside = in_repo_with_state(tmp_path / "app", state)
    code = init_repo(tmp_path / "code")
    apart = separate(tmp_path / "plan", code)

    # The view check proves the checks ran; the location check stays quiet in both.
    checks = checks_of(outside)
    assert [c.status for c in named(checks, VIEW)] == ["warn"]
    assert named(checks, LOCATION) == []
    assert named(checks_of(apart), LOCATION) == []


def test_a_state_inside_the_repository_is_reported_as_a_location_not_as_a_missing_link(
    tmp_path: Path,
) -> None:
    root = tmp_path / "app"
    config = in_repo_with_state(root, root / "runs")

    checks = checks_of(config)

    assert named(checks, VIEW) == []
    assert [c.status for c in named(checks, LOCATION)] == ["warn"]
