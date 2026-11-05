"""A restack keeps the changelog's form when the union merge joins two bullets.

`CHANGELOG.md merge=union` keeps a blank line that both branches added only once, so two
branches that each add a bullet at the same place come out with the bullets back to back.
These tests run against real git repositories with that attribute set.
"""

from pathlib import Path

from agent_build_kit.changelog_form import changelog_problems
from agent_build_kit.config import RepoConfig
from agent_build_kit.pipeline.restack import move_branch_onto
from tests.factories import git, init_repo

BASE = """\
# Changelog

## Unreleased

- Base thing.

## 0.1.0 — 2026-09-28

- First release.
"""
TOP = "## Unreleased\n\n"
END = "- Base thing.\n\n"
A_AT_TOP = BASE.replace(TOP, f"{TOP}- A thing.\n\n")
B_AT_TOP = BASE.replace(TOP, f"{TOP}- B thing.\n\n")
B_AT_END = BASE.replace(END, f"{END}- B thing.\n\n")


def _write_and_commit(repo: Path, name: str, text: str, message: str) -> None:
    (repo / name).parent.mkdir(parents=True, exist_ok=True)
    (repo / name).write_text(text)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)


def _union_repo(path: Path, name: str = "CHANGELOG.md") -> tuple[Path, str]:
    """A repo with a union-merged changelog on `main`; the repo and that first commit."""
    repo = init_repo(path)
    (repo / ".gitattributes").write_text(f"{name} merge=union\n")
    _write_and_commit(repo, name, BASE, "base")
    return repo, git(repo, "rev-parse", "HEAD").strip()


def _move(
    repo: Path,
    old_main: str,
    *,
    a_text: str,
    b_text: str,
    name: str = "CHANGELOG.md",
    config: RepoConfig | None = None,
) -> int:
    """Land `spec/a/1` on main, make `spec/b/1` from the old main, move it onto main;
    how many commits the move added to `spec/b/1`."""
    git(repo, "checkout", "-q", "-b", "spec/a/1")
    _write_and_commit(repo, name, a_text, "a")
    git(repo, "checkout", "-q", "main")
    git(repo, "merge", "-q", "--ff-only", "spec/a/1")
    git(repo, "checkout", "-q", "-b", "spec/b/1", old_main)
    _write_and_commit(repo, name, b_text, "b")
    git(repo, "checkout", "-q", "main")
    own = int(git(repo, "rev-list", "--count", f"{old_main}..spec/b/1").strip())

    move_branch_onto(repo, "spec/b/1", new_base="main", old_base=old_main, repo_config=config)

    return int(git(repo, "rev-list", "--count", "main..spec/b/1").strip()) - own


def test_bullets_the_union_merge_joined_are_separated_in_a_commit_of_their_own(
    tmp_path: Path,
) -> None:
    joined, joined_main = _union_repo(tmp_path / "joined")
    apart, apart_main = _union_repo(tmp_path / "apart")

    added = _move(joined, joined_main, a_text=A_AT_TOP, b_text=B_AT_TOP)
    added_when_apart = _move(apart, apart_main, a_text=A_AT_TOP, b_text=B_AT_END)

    moved = git(joined, "show", "spec/b/1:CHANGELOG.md")
    assert changelog_problems(moved) == []
    assert changelog_problems(git(apart, "show", "spec/b/1:CHANGELOG.md")) == []
    assert "- A thing." in moved
    assert "- B thing." in moved
    assert added == 1
    assert git(joined, "show", "--name-only", "--format=", "spec/b/1").split() == ["CHANGELOG.md"]
    assert added_when_apart == 0


def test_a_repo_with_its_changelog_setting_off_keeps_the_file_as_the_rebase_left_it(
    tmp_path: Path,
) -> None:
    repo, old_main = _union_repo(tmp_path / "off")
    config = RepoConfig(path=repo, changelog=None)
    # What the same rebase leaves with the convention on, as the unseparated file.
    reference, reference_main = _union_repo(tmp_path / "reference")
    _move(reference, reference_main, a_text=A_AT_TOP, b_text=B_AT_TOP)
    separated = git(reference, "show", "spec/b/1:CHANGELOG.md")

    added = _move(repo, old_main, a_text=A_AT_TOP, b_text=B_AT_TOP, config=config)

    left = git(repo, "show", "spec/b/1:CHANGELOG.md")
    assert added == 0
    assert left != separated
    assert changelog_problems(left) != []
    assert "- A thing.\n- B thing." in left or "- B thing.\n- A thing." in left


def test_the_file_the_repo_names_is_the_one_separated(tmp_path: Path) -> None:
    name = "docs/CHANGES.md"
    repo, old_main = _union_repo(tmp_path / "named", name)
    (repo / "CHANGELOG.md").write_text("- stray\n- compact\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "stray")
    old_main = git(repo, "rev-parse", "HEAD").strip()
    config = RepoConfig(path=repo, changelog=name)

    added = _move(repo, old_main, a_text=A_AT_TOP, b_text=B_AT_TOP, name=name, config=config)

    assert added == 1
    assert changelog_problems(git(repo, "show", f"spec/b/1:{name}")) == []
    assert git(repo, "show", "--name-only", "--format=", "spec/b/1").split() == [name]
    assert git(repo, "show", "spec/b/1:CHANGELOG.md") == "- stray\n- compact"
