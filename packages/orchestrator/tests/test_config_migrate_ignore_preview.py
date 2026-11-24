"""The `.gitignore` diff `abk config --migrate` previews is the change the write makes."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config_migrate_write import file_diff, ignore_diff, write_both
from agent_build_kit.pipeline.file_lock import with_missing_lines
from tests.config_migrate_write_fakes import BASE_NEW, LOCAL_NEW, files
from tests.factories import init_repo

# A line git reads as un-ignoring the file, so `git check-ignore` does not ignore it, while the
# text of the file already holds the line.
CONFUSING = "abk.local.yaml\n!abk.local.yaml\n"


@pytest.mark.parametrize("before", ["", "build", CONFUSING], ids=["none", "no-newline", "negated"])
def test_the_preview_is_the_diff_of_the_file_the_write_leaves(
    before: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    base, _ = files(tmp_path)
    init_repo(tmp_path)
    ignore = tmp_path / ".gitignore"
    if before:
        ignore.write_text(before)
    preview = ignore_diff(tmp_path)

    write_both(base, BASE_NEW, LOCAL_NEW, show_ignore_diff=False)

    written = ignore.read_text()
    assert preview == file_diff(ignore, before, written)
    capsys.readouterr()


def test_the_lines_a_text_lacks_are_added_once_after_a_missing_newline() -> None:
    assert with_missing_lines("a", ["b", "b", "a"]) == "a\nb\n"
    assert with_missing_lines("a\n", ["a"]) == "a\n"
