"""A unit's worktree is keyed by the repo's name in `abk.yaml`, and one that exists is found
through git and used where it is (spec: unit-worktrees)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from agent_build_kit.pipeline.workspaces import (
    WorktreeElsewhere,
    WorktreeOccupied,
    prepare_detached,
    prepare_worktree,
    remove_worktree,
    unit_tree,
    worktree_key,
    worktree_path,
)
from tests.factories import git, init_repo

BRANCH = "spec/x/1"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "app")
    (work / "README.md").write_text("base\n")
    git(work, "add", "-A")
    git(work, "commit", "-qm", "base")
    return work


@pytest.fixture
def root(tmp_path: Path) -> Path:
    return tmp_path / "trees"


def listing(repo: Path) -> str:
    return git(repo, "worktree", "list", "--porcelain")


def add_at(repo: Path, path: Path, branch: str = BRANCH) -> Path:
    """The branch, made on `main`, checked out at `path` by git itself."""
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "-q", "-b", branch, str(path), "main")
    return path


@pytest.mark.parametrize(("name", "key"), [("app", "app"), ("my-app", "my-app"), ("a b", "a_b")])
def test_the_key_keeps_letters_digits_dot_underscore_and_dash(name: str, key: str) -> None:
    assert worktree_key(name) == key


def test_the_path_is_named_for_the_repo_not_its_checkout(repo: Path, root: Path) -> None:
    assert worktree_path(repo, BRANCH, root, name="lib") == root / "lib" / "spec_x_1"


def test_a_key_equal_to_the_checkout_folder_gives_the_path_it_always_did(
    repo: Path, root: Path
) -> None:
    old = root / repo.name / "spec_x_1"

    assert worktree_path(repo, BRANCH, root, name="app") == old
    assert worktree_key("app") == repo.name


def test_a_worktree_under_an_earlier_folder_is_used_where_it_is(repo: Path, root: Path) -> None:
    old = add_at(repo, root / "worktree" / "spec_x_1")
    (old / "wip.txt").write_text("half done\n")
    before = listing(repo)

    got = prepare_worktree(repo, BRANCH, name="lib", base="main", root=root, allow_dirty=True)

    assert got == old
    assert not (root / "lib").exists()
    assert listing(repo) == before
    assert (old / "wip.txt").read_text() == "half done\n"
    assert unit_tree(repo, BRANCH, root) == old


def test_with_no_worktree_one_is_created_under_the_key(repo: Path, root: Path) -> None:
    assert unit_tree(repo, BRANCH, root) is None

    got = prepare_worktree(repo, BRANCH, name="lib", base="main", root=root)

    assert got == root / "lib" / "spec_x_1"
    assert unit_tree(repo, BRANCH, root) == got


def test_a_worktree_directory_deleted_by_hand_is_pruned_and_made_again(
    repo: Path, root: Path
) -> None:
    old = add_at(repo, root / "lib" / "spec_x_1")
    shutil.rmtree(old)
    assert unit_tree(repo, BRANCH, root) is None

    got = prepare_worktree(repo, BRANCH, name="lib", base="main", root=root)

    assert got == root / "lib" / "spec_x_1" and got.is_dir()
    assert listing(repo).count("worktree ") == 2


def test_a_branch_checked_out_in_the_checkout_is_refused_and_left(repo: Path, root: Path) -> None:
    git(repo, "checkout", "-q", "-b", BRANCH)
    (repo / "mine.txt").write_text("mine\n")
    head = git(repo, "rev-parse", "HEAD")

    with pytest.raises(WorktreeElsewhere) as refused:
        prepare_worktree(repo, BRANCH, name="lib", base="main", root=root)
    with pytest.raises(WorktreeElsewhere):
        remove_worktree(repo, BRANCH, root=root)

    assert BRANCH in str(refused.value) and str(repo) in str(refused.value)
    assert git(repo, "branch", "--show-current").strip() == BRANCH
    assert git(repo, "rev-parse", "HEAD") == head
    assert (repo / "mine.txt").exists()
    assert unit_tree(repo, BRANCH, root) is None


def test_a_branch_checked_out_outside_the_root_is_refused_and_left(
    repo: Path, root: Path, tmp_path: Path
) -> None:
    outside = add_at(repo, tmp_path / "elsewhere" / "spec_x_1")
    before = listing(repo)

    with pytest.raises(WorktreeElsewhere) as refused:
        prepare_worktree(repo, BRANCH, name="lib", base="main", root=root)
    with pytest.raises(WorktreeElsewhere):
        remove_worktree(repo, BRANCH, root=root)

    assert BRANCH in str(refused.value) and str(outside) in str(refused.value)
    assert listing(repo) == before and outside.is_dir()
    assert unit_tree(repo, BRANCH, root) is None


def test_two_branches_with_one_sanitised_name_are_refused(repo: Path, root: Path) -> None:
    first = add_at(repo, root / "lib" / "spec_a_b_1", "spec/a-b/1")
    before = listing(repo)

    with pytest.raises(WorktreeOccupied) as refused:
        prepare_worktree(repo, "spec/a_b/1", name="lib", base="main", root=root)

    assert "spec/a_b/1" in str(refused.value) and str(first) in str(refused.value)
    assert listing(repo) == before


def test_a_leftover_directory_with_files_is_refused_and_an_empty_one_is_used(
    repo: Path, root: Path
) -> None:
    target = root / "lib" / "spec_x_1"
    target.mkdir(parents=True)
    (target / "leftover.txt").write_text("not git's\n")

    with pytest.raises(WorktreeOccupied):
        prepare_worktree(repo, BRANCH, name="lib", base="main", root=root)
    assert (target / "leftover.txt").exists()

    (target / "leftover.txt").unlink()
    assert prepare_worktree(repo, BRANCH, name="lib", base="main", root=root) == target
    assert (target / "README.md").exists()


def test_removing_a_worktree_under_an_earlier_folder_keeps_the_branch(
    repo: Path, root: Path
) -> None:
    old = add_at(repo, root / "worktree" / "spec_x_1")

    remove_worktree(repo, BRANCH, root=root)

    assert not old.exists()
    assert git(repo, "branch", "--list", BRANCH).strip()


def test_a_dirty_worktree_under_an_earlier_folder_is_left_by_remove(repo: Path, root: Path) -> None:
    old = add_at(repo, root / "worktree" / "spec_x_1")
    (old / "wip.txt").write_text("unsaved\n")

    remove_worktree(repo, BRANCH, root=root)

    assert (old / "wip.txt").exists()
    assert unit_tree(repo, BRANCH, root) == old


def test_a_detached_checkout_under_an_earlier_folder_is_moved_to_the_ref(
    repo: Path, root: Path
) -> None:
    old = root / "worktree" / "_dev_stack_base"
    old.parent.mkdir(parents=True)
    git(repo, "worktree", "add", "-q", "--detach", str(old), "HEAD")
    (repo / "next.txt").write_text("next\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "next")
    before = listing(repo)

    got = prepare_detached(repo, "_dev_stack_base", name="lib", ref="main", root=root)

    assert got == old
    assert git(old, "rev-parse", "HEAD") == git(repo, "rev-parse", "main")
    assert not (root / "lib").exists()
    assert listing(repo).count("worktree ") == before.count("worktree ")


def test_a_detached_checkout_with_none_is_created_under_the_key(repo: Path, root: Path) -> None:
    got = prepare_detached(repo, "_dev_stack_base", name="lib", ref="main", root=root)

    assert got == root / "lib" / "_dev_stack_base"
    assert got.is_dir()
