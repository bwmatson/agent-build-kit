"""`abk tags --fix` rewrites the old test-kind tags of group headings and changes no other byte
(spec: tasks-tag-rewrite)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from tests.cli.tags_fix_support import (
    OLD_E2E_TAG,
    OLD_UNIT_TEST_TAG,
    line_about,
    one_group_text,
    planning,
    run_tags,
    tasks_text,
    write_change,
)

OLD = tasks_text(OLD_UNIT_TEST_TAG, OLD_E2E_TAG)
NEW = tasks_text("unit-test", "e2e-test")


def test_the_headings_are_rewritten_and_the_prose_is_not(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    path = write_change(run, "feature", OLD)

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 0, out
    # The sentence, the code span and the heading's title still say the old names.
    assert path.read_bytes() == NEW
    assert b"[unit-test] Add it" in path.read_bytes()
    assert b"[e2e-test] [acceptance]" in path.read_bytes()
    assert f"concern, see `{OLD_E2E_TAG}`".encode() in path.read_bytes()


def test_the_output_counts_the_tags_rewritten_in_each_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    write_change(run, "feature", OLD)
    write_change(run, "small", one_group_text(OLD_UNIT_TEST_TAG))

    code, out = run_tags(capsys, "--fix", "--all")

    assert code == 0, out
    assert "2 tag" in line_about(out, "feature")
    assert "1 tag" in line_about(out, "small")
    assert "would" not in out.lower()


def test_a_second_run_reports_the_change_unchanged_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    path = write_change(run, "feature", OLD)
    run_tags(capsys, "--fix", "feature")
    os.utime(path, ns=(1_000_000_000, 1_000_000_000))

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 0, out
    assert "unchanged" in line_about(out, "feature")
    assert path.read_bytes() == NEW
    assert path.stat().st_mtime_ns == 1_000_000_000


def test_carriage_return_line_endings_are_kept_on_every_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    path = write_change(run, "feature", tasks_text(OLD_UNIT_TEST_TAG, OLD_E2E_TAG, eol="\r\n"))

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 0, out
    assert path.read_bytes() == tasks_text("unit-test", "e2e-test", eol="\r\n")
    assert path.read_bytes().count(b"\n") == path.read_bytes().count(b"\r\n")


def test_a_file_with_no_trailing_newline_keeps_that(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    path = write_change(
        run, "feature", tasks_text(OLD_UNIT_TEST_TAG, OLD_E2E_TAG, final_newline=False)
    )

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 0, out
    assert path.read_bytes() == tasks_text("unit-test", "e2e-test", final_newline=False)
    assert not path.read_bytes().endswith(b"\n")


def test_all_rewrites_every_open_change_and_skips_the_archived(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    first = write_change(run, "first", OLD)
    second = write_change(run, "second", OLD)
    archived = write_change(run, "archive/2026-01-01-done", OLD)

    code, out = run_tags(capsys, "--fix", "--all")

    assert code == 0, out
    assert first.read_bytes() == NEW
    assert second.read_bytes() == NEW
    assert archived.read_bytes() == OLD
