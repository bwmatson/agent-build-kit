"""The `.planning` link: made, repaired, refused, and the check of where state lives."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.planning_view import (
    PlanningViewRefused,
    ensure_view,
    state_inside_repo,
    view_problem,
)
from tests.factories import git
from tests.planning_worktree_support import working_copy_of


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return working_copy_of(tmp_path / "repos", origin=False)[1]


@pytest.fixture
def state(tmp_path: Path) -> Path:
    return tmp_path / "home" / "planning" / "state"


def exclude_text(repo: Path) -> str:
    exclude = git(repo, "rev-parse", "--path-format=absolute", "--git-path", "info/exclude")
    return Path(exclude.strip()).read_text()


def test_a_first_call_makes_the_state_directory_and_an_absolute_link(
    repo: Path, state: Path
) -> None:
    assert ensure_view(repo, state, dry_run=False) == "created"

    assert state.is_dir()
    link = repo / ".planning"
    assert link.is_symlink()
    assert Path(link.readlink()) == state
    assert Path(link.readlink()).is_absolute()
    assert git(repo, "status", "--porcelain").strip() == ""


def test_the_exclude_line_is_there_once_after_two_calls_and_the_second_is_unchanged(
    repo: Path, state: Path
) -> None:
    ensure_view(repo, state, dry_run=False)

    assert ensure_view(repo, state, dry_run=False) == "unchanged"

    assert exclude_text(repo).splitlines().count("/.planning") == 1


def test_a_dangling_link_is_repointed(repo: Path, state: Path, tmp_path: Path) -> None:
    (repo / ".planning").symlink_to(tmp_path / "gone")

    assert ensure_view(repo, state, dry_run=False) == "repointed"

    assert Path((repo / ".planning").readlink()) == state
    assert view_problem(repo, state) is None


def test_a_link_to_a_path_that_no_longer_exists_is_repointed_after_its_target_is_removed(
    repo: Path, state: Path, tmp_path: Path
) -> None:
    old = tmp_path / "old-state"
    old.mkdir()
    (repo / ".planning").symlink_to(old)
    old.rmdir()

    assert ensure_view(repo, state, dry_run=False) == "repointed"

    assert Path((repo / ".planning").readlink()) == state


def test_a_dry_run_says_what_it_would_do_and_writes_nothing(repo: Path, state: Path) -> None:
    before = exclude_text(repo)

    assert ensure_view(repo, state, dry_run=True) == "would create"

    assert not state.exists()
    assert not (repo / ".planning").is_symlink()
    assert exclude_text(repo) == before


def test_a_dry_run_over_a_dangling_link_would_repoint_it_and_leaves_it(
    repo: Path, state: Path, tmp_path: Path
) -> None:
    (repo / ".planning").symlink_to(tmp_path / "gone")

    assert ensure_view(repo, state, dry_run=True) == "would repoint"

    assert Path((repo / ".planning").readlink()) == tmp_path / "gone"


def test_a_regular_file_is_refused_and_nothing_else_changes(repo: Path, state: Path) -> None:
    (repo / ".planning").write_text("mine\n")
    before = exclude_text(repo)

    with pytest.raises(PlanningViewRefused, match=r"\.planning"):
        ensure_view(repo, state, dry_run=False)

    assert (repo / ".planning").read_text() == "mine\n"
    assert not state.exists()
    assert exclude_text(repo) == before


def test_a_directory_with_a_file_is_refused_and_nothing_else_changes(
    repo: Path, state: Path
) -> None:
    (repo / ".planning").mkdir()
    (repo / ".planning" / "notes.md").write_text("mine\n")
    before = exclude_text(repo)

    with pytest.raises(PlanningViewRefused, match=r"\.planning"):
        ensure_view(repo, state, dry_run=False)

    assert (repo / ".planning" / "notes.md").read_text() == "mine\n"
    assert not state.exists()
    assert exclude_text(repo) == before


def test_a_link_to_another_existing_path_is_refused_and_left(
    repo: Path, state: Path, tmp_path: Path
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo / ".planning").symlink_to(elsewhere)
    before = exclude_text(repo)

    with pytest.raises(PlanningViewRefused, match=r"\.planning"):
        ensure_view(repo, state, dry_run=False)

    assert Path((repo / ".planning").readlink()) == elsewhere
    assert not state.exists()
    assert exclude_text(repo) == before


def test_a_right_link_has_no_problem(repo: Path, state: Path) -> None:
    ensure_view(repo, state, dry_run=False)

    assert view_problem(repo, state) is None


def test_a_missing_link_is_missing(repo: Path, state: Path) -> None:
    assert view_problem(repo, state) == "missing"


def test_a_dangling_link_is_dangling(repo: Path, state: Path, tmp_path: Path) -> None:
    (repo / ".planning").symlink_to(tmp_path / "gone")

    assert view_problem(repo, state) == "dangling"


def test_a_link_elsewhere_names_where_it_points(repo: Path, state: Path, tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (repo / ".planning").symlink_to(elsewhere)

    assert view_problem(repo, state) == f"points to {elsewhere}"


def test_a_file_or_directory_is_described_as_one(repo: Path, state: Path) -> None:
    (repo / ".planning").mkdir()

    problem = view_problem(repo, state)

    assert problem is not None
    assert "file or directory" in problem


def inside_args(repo: Path) -> tuple[Path, Path]:
    return repo, repo / ".git"


def test_a_directory_under_the_root_is_inside(repo: Path) -> None:
    state = repo / "data" / "state"
    state.mkdir(parents=True)

    assert state_inside_repo(state, *inside_args(repo)) == state.resolve()


def test_a_directory_under_the_git_directory_is_inside(repo: Path) -> None:
    state = repo / ".git" / "abk-state"
    state.mkdir()

    assert state_inside_repo(state, *inside_args(repo)) == state.resolve()


def test_a_directory_not_made_yet_under_the_root_is_inside(repo: Path) -> None:
    state = repo / "not" / "yet" / "made"

    assert state_inside_repo(state, *inside_args(repo)) == state.resolve()


def test_a_link_outside_the_repository_that_leads_into_it_is_inside(
    repo: Path, tmp_path: Path
) -> None:
    target = repo / "data"
    target.mkdir()
    link = tmp_path / "outside-link"
    link.symlink_to(target)

    assert state_inside_repo(link, *inside_args(repo)) == target.resolve()


def test_a_directory_outside_is_not_inside(repo: Path, state: Path) -> None:
    state.mkdir(parents=True)

    assert state_inside_repo(state, *inside_args(repo)) is None


def test_a_link_inside_the_repository_that_leads_outside_is_not_inside(
    repo: Path, state: Path
) -> None:
    state.mkdir(parents=True)
    link = repo / "state-link"
    link.symlink_to(state)

    assert state_inside_repo(link, *inside_args(repo)) is None


def test_a_root_in_a_subdirectory_excludes_its_own_path_and_leaves_the_tree_clean(
    repo: Path, state: Path
) -> None:
    sub = repo / "planning"
    sub.mkdir()
    (sub / "keep.md").write_text("x\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "sub")

    ensure_view(sub, state, dry_run=False)

    assert exclude_text(repo).splitlines().count("/planning/.planning") == 1
    assert git(repo, "status", "--porcelain").strip() == ""
