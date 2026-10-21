"""`abk tags --fix --dry-run` lists the rewrites and writes nothing, and `--fix` alone is a usage
error (spec: tasks-tag-rewrite)."""

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


def test_a_dry_run_lists_what_it_would_rewrite_and_writes_no_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    first = write_change(run, "feature", OLD)
    second = write_change(run, "small", one_group_text(OLD_UNIT_TEST_TAG))
    for path in (first, second):
        os.utime(path, ns=(1_000_000_000, 1_000_000_000))

    code, out = run_tags(capsys, "--fix", "--dry-run", "--all")

    assert code == 0, out
    assert "would" in line_about(out, "feature").lower()
    assert "2 tag" in line_about(out, "feature")
    assert "1 tag" in line_about(out, "small")
    assert first.read_bytes() == OLD
    assert second.read_bytes() == one_group_text(OLD_UNIT_TEST_TAG)
    assert first.stat().st_mtime_ns == second.stat().st_mtime_ns == 1_000_000_000


def test_fix_with_no_change_and_no_all_is_a_usage_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    path = write_change(run, "feature", OLD)

    code, out = run_tags(capsys, "--fix")

    assert code == 2
    assert "--fix" in out
    assert path.read_bytes() == OLD
