"""The document guards skip an archived change and still read `docs/` (spec: repo-wide-guards).

Each test calls the guard's own function on a temporary root.
"""

from __future__ import annotations

from pathlib import Path

from tests.docs.test_review_docs_status import documents, reported
from tests.old_merge_rule import statements
from tests.repo_docs import repo_markdown
from tests.test_live_test_names import OLD_STEMS, tracked_files

ARCHIVED = "openspec/changes/archive/2026-01-01-drop-key/proposal.md"


def write(root: Path, name: str, text: str) -> None:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def test_an_archived_change_naming_a_removed_key_is_not_reported_but_docs_is(
    tmp_path: Path,
) -> None:
    text = "`review.enabled` is removed.\n"
    write(tmp_path, ARCHIVED, text)
    write(tmp_path, "docs/a.md", text)

    reported_files = [
        path.relative_to(tmp_path).as_posix()
        for path in documents(root=tmp_path)
        if reported(path.read_text())
    ]

    assert reported_files == ["docs/a.md"]


def test_an_archived_change_stating_the_old_merge_rule_is_not_reported_but_docs_is(
    tmp_path: Path,
) -> None:
    text = "A person merges every pull request.\n"
    write(tmp_path, ARCHIVED, text)
    write(tmp_path, "docs/a.md", text)

    reported_files = [
        path.relative_to(tmp_path).as_posix()
        for path in repo_markdown(root=tmp_path)
        if statements(path.read_text())
    ]

    assert reported_files == ["docs/a.md"]


def test_an_archived_change_naming_an_old_module_is_not_reported_but_docs_is(
    tmp_path: Path,
) -> None:
    text = f"{OLD_STEMS[0]} was renamed.\n"
    write(tmp_path, ARCHIVED, text)
    write(tmp_path, "docs/a.md", text)

    reported_files = [
        path.relative_to(tmp_path).as_posix()
        for path in tracked_files(root=tmp_path)
        if OLD_STEMS[0] in path.read_text()
    ]

    assert reported_files == ["docs/a.md"]
