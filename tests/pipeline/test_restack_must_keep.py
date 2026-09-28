"""Working out what a resolution must not delete.

`must_keep` guards against the easiest wrong resolution: making the conflict
vanish by taking the base's side, which empties the unit being moved. The
caller shouldn't have to hand-write that guard, so it is derived from the
moving branch's own diff — the lines it added that the base doesn't have.

The derivation has to be conservative in a specific direction. A marker that
is really the base's (not distinctive) would fail every resolution and stall
the pipeline; that is worse than a marker too weak to catch a bad one, because
the checks afterwards — tier 1, tier 2, review — still have to pass.
"""

from pathlib import Path

import pytest

from agent_build_kit.pipeline.restack import derive_must_keep
from tests.factories import git, init_repo


def commit(repo: Path, name: str, content: str) -> None:
    (repo / name).write_text(content)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", f"write {name}")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    work = init_repo(tmp_path / "repo")
    commit(work, "markers.py", "markers = []\n")
    git(work, "checkout", "-q", "-b", "spec/c/1")
    return work


def test_a_line_the_branch_added_becomes_the_marker(repo: Path) -> None:
    commit(repo, "markers.py", 'markers = ["local_stack"]\n')

    keep = derive_must_keep(repo, "spec/c/1", old_base="main", files=["markers.py"])

    assert any("local_stack" in item for item in keep)


def test_a_line_the_base_already_has_is_not_distinctive(repo: Path) -> None:
    """Requiring something the base supplies would fail every resolution and
    stall the stack, which is worse than a weak guard."""
    commit(repo, "markers.py", "markers = []\nunrelated = 1\n")
    git(repo, "checkout", "-q", "main")
    commit(repo, "markers.py", "markers = []\nunrelated = 1\n")
    git(repo, "checkout", "-q", "spec/c/1")

    keep = derive_must_keep(repo, "spec/c/1", old_base="main", files=["markers.py"])

    assert not any("unrelated" in item for item in keep)


def test_trivial_lines_are_not_markers(repo: Path) -> None:
    """Blank lines, braces and one-token lines appear everywhere; requiring
    one proves nothing about the unit's change surviving."""
    commit(repo, "markers.py", "markers = []\n\n\n)\nx\n")

    keep = derive_must_keep(repo, "spec/c/1", old_base="main", files=["markers.py"])

    assert all(len(item) > 4 for item in keep)
    assert ")" not in keep


def test_only_conflicted_files_are_considered(repo: Path) -> None:
    """A marker from an untouched file would be trivially satisfied, so the
    guard would never fire."""
    commit(repo, "markers.py", 'markers = ["local_stack"]\n')
    commit(repo, "other.py", "elsewhere = 'not in the conflict'\n")

    keep = derive_must_keep(repo, "spec/c/1", old_base="main", files=["markers.py"])

    assert not any("elsewhere" in item for item in keep)


def test_the_marker_list_is_capped(repo: Path) -> None:
    """Every marker is another way for a legitimate resolution to be refused."""
    body = "".join(f"distinctive_line_number_{n} = {n}\n" for n in range(20))
    commit(repo, "markers.py", body)

    keep = derive_must_keep(repo, "spec/c/1", old_base="main", files=["markers.py"])

    assert 0 < len(keep) <= 3


def test_a_branch_that_added_nothing_distinctive_yields_no_markers(repo: Path) -> None:
    """Whitespace and one-token lines only. The check then doesn't fire, and
    tier 1, tier 2 and the review pass are what catch a bad resolution."""
    commit(repo, "markers.py", "markers = []\n\n)\n")

    assert derive_must_keep(repo, "spec/c/1", old_base="main", files=["markers.py"]) == []


def test_a_deleted_file_does_not_break_the_derivation(repo: Path) -> None:
    (repo / "markers.py").unlink()
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "remove markers")

    assert derive_must_keep(repo, "spec/c/1", old_base="main", files=["markers.py"]) == []
