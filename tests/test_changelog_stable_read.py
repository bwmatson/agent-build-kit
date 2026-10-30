"""A changelog read mid-write is read again, so the check never sees half a file."""

from collections.abc import Callable, Iterator
from pathlib import Path

from agent_build_kit.changelog_form import changelog_file_problems

COMPLETE = """\
# Changelog

## Unreleased

- A new thing, described for someone using the tool.

- Another thing, with its reason.
"""

# A write caught half way: the first bullet is cut off, and the second runs into it.
PARTIAL = (
    "# Changelog\n\n## Unreleased\n\n- A new thing, described for someone using the tool.\n- Anoth"
)


def reads_in_turn(*texts: str) -> Callable[[Path], str]:
    turns: Iterator[str] = iter(texts)
    return lambda _path: next(turns)


def test_a_read_caught_mid_write_is_repeated_until_two_reads_agree(tmp_path: Path) -> None:
    read = reads_in_turn(PARTIAL, COMPLETE, COMPLETE)

    assert changelog_file_problems(tmp_path / "CHANGELOG.md", read=read) == []


def test_a_changelog_that_is_wrong_and_steady_still_reports_its_problems(tmp_path: Path) -> None:
    broken = COMPLETE.replace("\n- Another", "- Another")
    read = reads_in_turn(broken, broken)

    problems = changelog_file_problems(tmp_path / "CHANGELOG.md", read=read)

    assert any("not separated by a blank line" in problem for problem in problems)
