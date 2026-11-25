"""The helper that yields the tracked files a repo-wide guard reads (spec: repo-wide-guards).

One table specifies it: each row is a tree, whether it is a git repository (its files committed, a
few left untracked or deleted from the disk), how many `ls-files` listings a fake git refuses
(`rev-parse` is always refused, as on a loaded machine), the call and the expected result. A failed
listing never widens the set to files git does not track, and a vanished file is not listed. A
second test reads the real checkout, so a helper that yields nothing cannot pass the guards that
use it unnoticed.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from tests import tracked_files
from tests.factories import commit_files, init_repo
from tests.installation_leaks import foreign_slug_owners, hits
from tests.time_limit import LOADED_TEST_TIME_LIMIT
from tests.tracked_files import guarded_files, planning_dirs, tracked

TREE = {
    "docs/a.md": "a\n",
    "docs/b.txt": "b\n",
    "src/m.py": "m\n",
    "README.md": "r\n",
    "openspec/changes/x/proposal.md": "p\n",
    "runs/notes.md": "n\n",
    "runs/units.json": "{}\n",
    "node_modules/b.md": "b\n",
    ".hidden/c.md": "c\n",
}
LEAKY = "see https://github.com/" + "someone-real/repo\n"
CLEAN = {"src/clean.py": "x = 1\n"}


class Row(NamedTuple):
    files: dict[str, str]
    call: Callable[[Path], Any]
    expected: Any
    git: bool = False
    untracked: dict[str, str] = {}
    deleted: tuple[str, ...] = ()
    refused_listings: int = 0


def relative(root: Path, found: list[Path]) -> list[str]:
    return [path.relative_to(root).as_posix() for path in found]


def listed(**arguments: Any) -> Callable[[Path], list[str]]:
    """The call `guarded_files(root, **arguments)`, as paths relative to the root."""
    return lambda root: relative(root, guarded_files(root, **arguments))


def dirs(root: Path) -> tuple[str, str]:
    found = planning_dirs(root)
    return (found.specs_dir, found.state_dir)


def raises(root: Path) -> type[BaseException] | None:
    try:
        tracked(root)
    except subprocess.CalledProcessError as error:
        return type(error)
    return None


PLANNING = {
    "abk.yaml": "planning:\n  specs_dir: specs\n  state_dir: state\n",
    "specs/c.md": "c\n",
    "openspec/d.md": "d\n",
    "state/e.md": "e\n",
    "runs/f.md": "f\n",
}

ROWS: dict[str, Row] = {
    "planning content is left out by default": Row(
        TREE, listed(suffixes=[".md"], specs=False), ["README.md", "docs/a.md"]
    ),
    "the specification folder is added on request and the state folder is not": Row(
        TREE,
        listed(suffixes=[".md"], specs=True),
        ["README.md", "docs/a.md", "openspec/changes/x/proposal.md"],
    ),
    "under is sorted and spans folders": Row(
        TREE, listed(under=["src", "docs"]), ["docs/a.md", "docs/b.txt", "src/m.py"]
    ),
    "suffixes narrow the files under a folder": Row(
        TREE, listed(under=["docs"], suffixes=[".txt"]), ["docs/b.txt"]
    ),
    "names add root files and an absent name is skipped": Row(
        TREE,
        listed(under=["src"], names=["README.md", "absent.md"]),
        ["README.md", "src/m.py"],
    ),
    "a root file named under the state folder is yielded": Row(
        TREE,
        listed(under=["docs"], names=["runs/units.json"]),
        ["docs/a.md", "docs/b.txt", "runs/units.json"],
    ),
    "the planning folders come from abk.yaml without the specification folder": Row(
        PLANNING, listed(suffixes=[".md"]), ["openspec/d.md", "runs/f.md"]
    ),
    "the planning folders come from abk.yaml with the specification folder on request": Row(
        PLANNING, listed(suffixes=[".md"], specs=True), ["openspec/d.md", "runs/f.md", "specs/c.md"]
    ),
    "the configured planning folders are read": Row(PLANNING, dirs, ("specs", "state")),
    "a missing abk.yaml gives the default planning folders": Row({}, dirs, ("openspec", "runs")),
    "an unset state folder gives the default": Row(
        {"abk.yaml": "planning:\n  specs_dir: specs\n"}, dirs, ("specs", "runs")
    ),
    "the test trees are the root tests and each package tests that exists": Row(
        {"tests/a.py": "", "packages/one/tests/b.py": "", "packages/two/src/c.py": ""},
        tracked_files.test_tree_folders,
        ["tests", "packages/one/tests"],
    ),
    "in a git repository an untracked file is not yielded": Row(
        {"docs/tracked.md": "t\n"},
        listed(suffixes=[".md"]),
        ["docs/tracked.md"],
        git=True,
        untracked={"docs/untracked.md": "u\n"},
    ),
    "outside a git repository the tree is walked": Row(
        {"docs/loose.md": "l\n"}, listed(suffixes=[".md"]), ["docs/loose.md"]
    ),
    "a failed listing is tried again and adds no untracked file": Row(
        CLEAN,
        tracked,
        [Path("src/clean.py")],
        git=True,
        untracked={"src/untracked.py": LEAKY},
        refused_listings=1,
    ),
    "a listing that keeps failing raises and does not walk the tree": Row(
        CLEAN,
        raises,
        subprocess.CalledProcessError,
        git=True,
        untracked={"src/untracked.py": LEAKY},
        refused_listings=1000,
    ),
    "the slug scan gives the same result when the first listing fails": Row(
        CLEAN,
        lambda root: hits(root, foreign_slug_owners),
        [],
        git=True,
        untracked={"src/untracked.py": LEAKY},
        refused_listings=1,
    ),
    "a tracked file missing from the disk is not listed": Row(
        {"src/kept.py": "x = 1\n", "src/gone.py": "y = 2\n"},
        listed(under=["src"]),
        ["src/kept.py"],
        git=True,
        deleted=("src/gone.py",),
    ),
}


def refuse_git(monkeypatch: pytest.MonkeyPatch, *, listings: int) -> None:
    """Make the first `listings` calls of `ls-files` fail, and every `rev-parse`."""
    real = tracked_files.git
    refused = 0

    def git(repo: Path, *args: str, **kwargs: Any) -> subprocess.CompletedProcess[str]:
        nonlocal refused
        listing = args[:1] == ("ls-files",)
        if args[:1] == ("rev-parse",) or (listing and refused < listings):
            refused += listing
            return subprocess.CompletedProcess(["git", *args], 128, stdout="", stderr="busy")
        return real(repo, *args, **kwargs)

    monkeypatch.setattr(tracked_files, "git", git)


def write(root: Path, files: dict[str, str]) -> None:
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


@pytest.mark.parametrize("name", ROWS, ids=list(ROWS))
def test_the_helper_yields_what_the_row_expects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    row = ROWS[name]
    if row.git:
        init_repo(tmp_path)
        commit_files(tmp_path, "start", row.files)
    else:
        write(tmp_path, row.files)
    write(tmp_path, row.untracked)
    for gone in row.deleted:
        (tmp_path / gone).unlink()
    if row.refused_listings:
        refuse_git(monkeypatch, listings=row.refused_listings)

    assert row.call(tmp_path) == row.expected


@pytest.mark.time_limit(LOADED_TEST_TIME_LIMIT)
@pytest.mark.integration
def test_the_helper_yields_files_of_the_real_checkout() -> None:
    assert len(guarded_files(suffixes=[".py"])) > 0
    assert "packages/worker/tests" in tracked_files.test_tree_folders()
