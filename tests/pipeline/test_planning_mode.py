"""The role of a planning root, and the pipeline marker in the common git directory."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.planning_sync import (
    PlanningMode,
    live_pipeline_worktree,
    marker_path,
    planning_mode,
    read_pipeline_marker,
    remove_pipeline_marker,
    write_pipeline_marker,
)
from agent_build_kit.pipeline.shell import git as run_git
from tests.factories import git, init_repo
from tests.planning_worktree_support import InRepo, in_repo, installation_at


def unmarked(base: Path) -> InRepo:
    setup = in_repo(base)
    remove_pipeline_marker(setup.working_copy)
    return setup


def test_a_root_whose_repos_are_other_repositories_is_separate(tmp_path: Path) -> None:
    other = init_repo(tmp_path / "other")
    planning = init_repo(tmp_path / "planning")

    assert planning_mode(installation_at(planning, other)) == PlanningMode.SEPARATE


def test_a_root_that_is_no_git_repository_is_separate(tmp_path: Path) -> None:
    other = init_repo(tmp_path / "other")
    root = tmp_path / "plain"
    root.mkdir()

    assert planning_mode(installation_at(root, other)) == PlanningMode.SEPARATE


def test_a_root_in_a_listed_repos_repository_with_no_marker_is_a_working_copy(
    tmp_path: Path,
) -> None:
    setup = unmarked(tmp_path)
    inst = installation_at(setup.working_copy, setup.working_copy)

    assert planning_mode(inst) == PlanningMode.WORKING_COPY
    assert live_pipeline_worktree(inst) is None


def test_the_path_the_marker_names_is_the_pipeline_worktree(tmp_path: Path) -> None:
    setup = in_repo(tmp_path)

    inst = installation_at(setup.worktree, setup.working_copy)

    assert planning_mode(inst) == PlanningMode.PIPELINE_WORKTREE


def test_the_main_working_tree_is_a_working_copy_that_names_the_live_worktree(
    tmp_path: Path,
) -> None:
    setup = in_repo(tmp_path)

    inst = installation_at(setup.working_copy, setup.working_copy)

    assert planning_mode(inst) == PlanningMode.WORKING_COPY
    assert live_pipeline_worktree(inst) == setup.worktree


def test_a_marker_naming_a_missing_directory_makes_nothing_live(tmp_path: Path) -> None:
    setup = in_repo(tmp_path)
    git(setup.working_copy, "worktree", "remove", "--force", str(setup.worktree))
    assert not setup.worktree.exists()

    inst = installation_at(setup.working_copy, setup.working_copy)

    assert planning_mode(inst) == PlanningMode.WORKING_COPY
    assert live_pipeline_worktree(inst) is None


def test_the_marker_is_one_file_in_the_common_git_directory(tmp_path: Path) -> None:
    setup = unmarked(tmp_path)
    common = Path(
        git(setup.working_copy, "rev-parse", "--path-format=absolute", "--git-common-dir")
    )
    before = run_git(setup.working_copy, "status", "--porcelain").stdout

    written = write_pipeline_marker(setup.working_copy, setup.worktree)

    assert written == common / "abk-pipeline-worktree"
    assert marker_path(setup.working_copy) == written
    assert marker_path(setup.worktree) == written
    assert Path(written.read_text().strip()) == setup.worktree
    assert read_pipeline_marker(setup.working_copy) == setup.worktree
    assert read_pipeline_marker(setup.worktree) == setup.worktree
    assert run_git(setup.working_copy, "status", "--porcelain").stdout == before
    assert run_git(setup.worktree, "status", "--porcelain").stdout == ""

    remove_pipeline_marker(setup.working_copy)

    assert not written.exists()
    assert read_pipeline_marker(setup.working_copy) is None
    assert run_git(setup.working_copy, "status", "--porcelain").stdout == before


def test_removing_an_absent_marker_changes_nothing(tmp_path: Path) -> None:
    setup = unmarked(tmp_path)

    remove_pipeline_marker(setup.working_copy)

    assert read_pipeline_marker(setup.working_copy) is None
