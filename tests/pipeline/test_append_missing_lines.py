"""`append_missing_lines` adds what a text file lacks, once, and says whether it wrote."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.file_lock import append_missing_lines


def test_a_missing_file_is_created_with_the_lines(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "ignore"

    assert append_missing_lines(path, ["a", "b"]) is True

    assert path.read_text() == "a\nb\n"


def test_a_file_with_no_trailing_newline_gets_a_separator(tmp_path: Path) -> None:
    path = tmp_path / "ignore"
    path.write_text("a")

    assert append_missing_lines(path, ["b"]) is True

    assert path.read_text() == "a\nb\n"


def test_a_line_already_present_is_not_added_and_nothing_is_written(tmp_path: Path) -> None:
    path = tmp_path / "ignore"
    path.write_text("a\n  b  \n")

    assert append_missing_lines(path, ["a", "b"]) is False

    assert path.read_text() == "a\n  b  \n"


def test_only_the_missing_lines_are_added_once(tmp_path: Path) -> None:
    path = tmp_path / "ignore"
    path.write_text("a\n")

    assert append_missing_lines(path, ["a", "b", "b"]) is True

    assert path.read_text() == "a\nb\n"
