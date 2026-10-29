"""A failed `git ls-files` inside a repository never widens the set of files a guard reads.

The slug scan over the whole repository failed under parallel load and passed alone: when git
failed once to list the files, the list fell back to walking the tree, which includes files git
does not track. The failure is made here by a fake git that refuses listings and every
`rev-parse`, so no test waits on load to see it.
"""

import subprocess
from pathlib import Path

import pytest

from tests import tracked_files
from tests.factories import commit_files, init_repo
from tests.installation_leaks import foreign_slug_owners, hits
from tests.tracked_files import tracked

LEAKY = "see https://github.com/" + "someone-real/repo\n"


def _refuse_git(monkeypatch: pytest.MonkeyPatch, *, listings: int) -> None:
    """Make the first `listings` calls of `ls-files` fail, and every `rev-parse`, as a loaded
    machine can."""
    real = tracked_files.git
    refused = 0

    def git(repo: Path, *args: str, **kwargs):
        nonlocal refused
        listing = args[:1] == ("ls-files",)
        if args[:1] == ("rev-parse",) or (listing and refused < listings):
            refused += listing
            return subprocess.CompletedProcess(["git", *args], 128, stdout="", stderr="busy")
        return real(repo, *args, **kwargs)

    monkeypatch.setattr(tracked_files, "git", git)


def _repo_with_an_untracked_leak(root: Path) -> Path:
    init_repo(root)
    commit_files(root, "init", {"src/clean.py": "x = 1\n"})
    (root / "src" / "untracked.py").write_text(LEAKY)
    return root


def test_a_failed_listing_inside_a_repository_is_tried_again_and_adds_no_untracked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo_with_an_untracked_leak(tmp_path)
    _refuse_git(monkeypatch, listings=1)

    assert tracked(root) == [Path("src/clean.py")]


def test_a_listing_that_keeps_failing_inside_a_repository_raises_and_does_not_walk_the_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo_with_an_untracked_leak(tmp_path)
    _refuse_git(monkeypatch, listings=1000)

    with pytest.raises(subprocess.CalledProcessError):
        tracked(root)


def test_the_slug_scan_gives_the_same_result_when_the_first_listing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo_with_an_untracked_leak(tmp_path)
    _refuse_git(monkeypatch, listings=1)

    assert hits(root, foreign_slug_owners) == []
