"""A forward alias, which gives a name its new spelling before its file is converted, is dropped
when the tool converts that file, and the old and new names still both reach the class."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from agent_build_kit import rename_test_kinds
from tests.factories import commit_files, init_repo

MODULE = (
    f"class Tier2Split:\n    pass\n\n\nE2eSplit = Tier2Split  {rename_test_kinds.FORWARD_MARKER}\n"
)
CHECK = (
    "import sys; sys.path.insert(0, {root!r})\n"
    "import pkg.mod as mod\n"
    "assert mod.Tier2Split is mod.E2eSplit\n"
    "print('resolved')\n"
)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = init_repo(tmp_path / "repo")
    commit_files(root, "seed", {"pkg/__init__.py": "", "pkg/mod.py": MODULE})
    return root


def resolves(repo: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-I", "-c", CHECK.format(root=str(repo))],
        capture_output=True,
        text=True,
        check=False,
    )


def test_the_forward_alias_resolves_before_the_file_is_converted(repo: Path) -> None:
    assert resolves(repo).returncode == 0


def test_converting_the_file_drops_the_forward_alias_and_both_names_reach_the_class(
    repo: Path,
) -> None:
    rename_test_kinds.rename_paths(repo, [repo / "pkg"], shims=True)

    text = (repo / "pkg/mod.py").read_text()
    assert rename_test_kinds.FORWARD_MARKER not in text
    assert "class E2eSplit" in text
    result = resolves(repo)
    assert result.returncode == 0, result.stderr
    assert "resolved" in result.stdout


def test_a_second_run_changes_nothing(repo: Path) -> None:
    rename_test_kinds.rename_paths(repo, [repo / "pkg"], shims=True)

    assert rename_test_kinds.rename_paths(repo, [repo / "pkg"], shims=True) == []


def test_remove_shims_drops_a_forward_alias_whole(repo: Path) -> None:
    changed = rename_test_kinds.rename_paths(repo, [repo / "pkg"], remove_shims=True)

    assert changed == [Path("pkg/mod.py")]
    assert "E2eSplit" not in (repo / "pkg/mod.py").read_text()
