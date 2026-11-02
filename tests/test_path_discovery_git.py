from pathlib import Path

import pytest

from agent_build_kit.path_discovery import checkout_root, nearest_existing
from agent_build_kit.pipeline.shell import git
from tests.factories import init_repo
from tests.time_limit import LOADED_TEST_TIME_LIMIT
from tests.tracked_files import ROOT, guarded_files

MODULE = ROOT / "src" / "agent_build_kit" / "path_discovery.py"


def test_nearest_existing_for_folder_file_and_missing_path(tmp_path: Path):
    folder = init_repo(tmp_path / "repo")
    file = folder / "file.txt"
    file.write_text("x")
    assert nearest_existing(folder) == folder
    assert nearest_existing(file) == folder
    assert nearest_existing(folder / "a" / "b") == folder


def test_checkout_root_of_a_path_that_does_not_exist_yet(tmp_path: Path):
    repo = init_repo(tmp_path / "repo")
    (repo / "nested").mkdir()
    found = checkout_root(repo / "nested" / "new" / "file.txt")
    assert found is not None and found.resolve() == repo.resolve()


def test_linked_worktree_has_its_own_root(tmp_path: Path):
    repo = init_repo(tmp_path / "repo")
    (repo / "f").write_text("x")
    git(repo, "add", "f")
    git(repo, "commit", "-q", "-m", "init")
    linked = tmp_path / "linked"
    git(repo, "worktree", "add", "-q", str(linked), "-b", "other")
    (linked / "sub").mkdir()
    found = checkout_root(linked / "sub")
    assert found is not None and found.resolve() == linked.resolve()


def test_folder_in_no_repository_is_none(tmp_path: Path):
    outside = tmp_path / "plain"
    outside.mkdir()
    assert checkout_root(outside) is None


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
def test_only_the_module_asks_git_for_the_root():
    holders = [
        path
        for path in guarded_files(under=["src"], suffixes=[".py"])
        if "--show-toplevel" in path.read_text()
    ]
    assert holders == [MODULE]
