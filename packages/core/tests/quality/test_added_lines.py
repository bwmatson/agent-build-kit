"""The reading of a unit's added lines: merge-base, every kind of change, closed to tampering."""

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.pipeline.shell import git
from agent_build_kit.quality.added_lines import AddedLinesError, read_added_lines
from tests.factories import commit_files, init_repo, write_files

TEN = "".join(f"line {number}\n" for number in range(1, 11))


def repo_on_main(path: Path, files: dict[str, str]) -> Path:
    """A repository whose `main` holds the files in one commit, checked out on a new `unit`
    branch."""
    init_repo(path)
    commit_files(path, "base", files)
    git(path, "switch", "-q", "-c", "unit")
    return path


def test_a_unit_reads_as_the_lines_it_added_since_the_merge_base(tmp_path: Path) -> None:
    repo = repo_on_main(
        tmp_path / "repo",
        {"a.py": "x = 1\ny = 2\n", "c.py": "c = 1\n", "old_name.py": TEN, "keep.txt": "k\n"},
    )
    git(repo, "switch", "-q", "main")
    commit_files(repo, "main moves on", {"main_later.py": "later = 1\n"})
    git(repo, "switch", "-q", "unit")
    commit_files(repo, "add", {"a.py": "x = 1\ny = 2\nz = 3\n", "b.py": "b = 1\nb = 2\n"})
    commit_files(
        repo,
        "rename",
        {"new_name.py": TEN.replace("line 4\n", "line four\n")},
        rename={"old_name.py": "new_name.py"},
    )
    write_files(repo, {"c.py": "c = 1\nc = 2\n", "fresh.py": "f = 1\nf = 2\nf = 3\n"})

    reading = read_added_lines(repo, "main")

    assert {name: file.added for name, file in reading.items()} == {
        "a.py": frozenset({3}),
        "b.py": frozenset({1, 2}),
        "c.py": frozenset({2}),
        "fresh.py": frozenset({1, 2, 3}),
        "new_name.py": frozenset({4}),
    }
    assert {name for name, file in reading.items() if file.is_new} == {"b.py", "fresh.py"}
    assert reading["new_name.py"].renamed_from == "old_name.py"
    assert reading["new_name.py"].removed == ("line 4",)
    assert reading["a.py"].renamed_from is None


def hide_with_binary_attribute(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_files(repo, {".gitattributes": "*.py binary\n"})


def hide_with_no_diff_attribute(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_files(repo, {".gitattributes": "*.py -diff\n"})


def hide_with_textconv(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_files(repo, {".gitattributes": "*.py diff=quiet\n"})
    git(repo, "config", "diff.quiet.textconv", "true")


def hide_with_external_diff(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_EXTERNAL_DIFF", "true")


def hide_with_no_prefix(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git(repo, "config", "diff.noprefix", "true")


def hide_with_custom_prefixes(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    git(repo, "config", "diff.srcPrefix", "old/")
    git(repo, "config", "diff.dstPrefix", "new/")


@pytest.mark.parametrize(
    "hide",
    [
        hide_with_binary_attribute,
        hide_with_no_diff_attribute,
        hide_with_textconv,
        hide_with_external_diff,
        hide_with_no_prefix,
        hide_with_custom_prefixes,
    ],
)
def test_nothing_configured_in_the_checkout_hides_an_added_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hide: Callable[[Path, pytest.MonkeyPatch], None],
) -> None:
    repo = repo_on_main(tmp_path / "repo", {"a.py": "x = 1\ny = 2\n"})
    write_files(repo, {"a.py": "x = 1\ny = 2\nz = 3  # noqa\n"})
    hide(repo, monkeypatch)

    reading = read_added_lines(repo, "main")

    assert reading["a.py"].added == frozenset({3})


def test_an_untracked_file_is_read_only_when_it_is_a_text_file_inside_the_checkout(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside.txt"
    outside.write_text("secret\n")
    repo = repo_on_main(tmp_path / "repo", {"a.py": "x = 1\n"})
    (repo / "link.txt").symlink_to(outside)
    (repo / "blob.dat").write_bytes(b"text\0binary\n")
    write_files(repo, {"plain.py": "p = 1\n"})

    reading = read_added_lines(repo, "main")

    assert set(reading) == {"plain.py"}


def test_lines_are_numbered_as_git_numbers_them_and_a_deleted_file_keeps_its_removed_lines(
    tmp_path: Path,
) -> None:
    repo = repo_on_main(tmp_path / "repo", {"gone.py": "keep = 1\nold = 2\n"})
    (repo / "gone.py").unlink()
    write_files(repo, {"odd.txt": "a\x0cb c\nd\r\ne\n"})

    reading = read_added_lines(repo, "main")

    assert reading["odd.txt"].added == frozenset({1, 2, 3})
    assert reading["gone.py"].deleted
    assert reading["gone.py"].added == frozenset()
    assert reading["gone.py"].removed == ("keep = 1", "old = 2")


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a file whatever its mode")
def test_an_untracked_file_the_process_cannot_read_raises_the_error_naming_it(
    tmp_path: Path,
) -> None:
    repo = repo_on_main(tmp_path / "repo", {"a.py": "x = 1\n"})
    write_files(repo, {"locked.py": "p = 1\n"})
    (repo / "locked.py").chmod(0)

    with pytest.raises(AddedLinesError, match="locked.py"):
        read_added_lines(repo, "main")


def unrelated_history(repo: Path) -> str:
    """A commit that shares no history with HEAD."""
    empty_tree = git(repo, "hash-object", "-t", "tree", "/dev/null").stdout.strip()
    return git(repo, "commit-tree", empty_tree, "-m", "orphan").stdout.strip()


@pytest.mark.parametrize(
    "resolve_base", [lambda repo: "no-such-ref", unrelated_history], ids=["unresolved", "unrelated"]
)
def test_a_base_with_no_merge_base_raises_the_error_naming_the_step_and_the_base(
    tmp_path: Path, resolve_base: Callable[[Path], str]
) -> None:
    repo = repo_on_main(tmp_path / "repo", {"a.py": "x = 1\n"})
    base = resolve_base(repo)

    with pytest.raises(AddedLinesError) as raised:
        read_added_lines(repo, base)

    assert "merge-base" in str(raised.value)
    assert base in str(raised.value)
