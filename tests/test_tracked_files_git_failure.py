"""A failed `git ls-files` inside a repository never widens the set of files a guard reads.

The slug scan over the whole repository failed under parallel load and passed alone: when git
failed once to list the files, the list fell back to walking the tree, which includes files git
does not track. The failure is made here by a fake git that refuses the first listing, so no
test waits on load to see it.
"""

import subprocess
from pathlib import Path

import pytest

from tests import tracked_files
from tests.factories import commit_files, init_repo
from tests.installation_leaks import foreign_slug_owners, hits
from tests.tracked_files import tracked

LEAKY = "see https://github.com/someone-real/repo\n"


def _fail_first_listing(monkeypatch: pytest.MonkeyPatch) -> None:
    real = tracked_files.git
    refused = False

    def git(repo: Path, *args: str, **kwargs):
        nonlocal refused
        if args[:1] == ("ls-files",) and not refused:
            refused = True
            return subprocess.CompletedProcess(["git", *args], 128, stdout="", stderr="busy")
        return real(repo, *args, **kwargs)

    monkeypatch.setattr(tracked_files, "git", git)


def _repo_with_an_untracked_leak(root: Path) -> Path:
    init_repo(root)
    commit_files(root, "init", {"src/clean.py": "x = 1\n"})
    (root / "src" / "untracked.py").write_text(LEAKY)
    return root


def test_a_failed_listing_inside_a_repository_does_not_add_untracked_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo_with_an_untracked_leak(tmp_path)
    _fail_first_listing(monkeypatch)

    try:
        listed = tracked(root)
    except (OSError, subprocess.CalledProcessError):
        return

    assert Path("src/untracked.py") not in listed


def test_the_slug_scan_gives_the_same_result_when_the_first_listing_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _repo_with_an_untracked_leak(tmp_path)
    _fail_first_listing(monkeypatch)

    try:
        found = hits(root, foreign_slug_owners)
    except (OSError, subprocess.CalledProcessError):
        return

    assert found == []
