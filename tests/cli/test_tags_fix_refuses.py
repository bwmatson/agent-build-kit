"""`abk tags --fix` refuses a change it cannot be sure of and writes nothing for it
(spec: tasks-tag-rewrite)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from agent_build_kit.pipeline import work_graph
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
UNKNOWN_REPO = OLD.replace(b"## 2. [app]", b"## 2. [nowhere]")


def test_a_change_with_another_tag_error_is_refused_with_that_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    path = write_change(run, "feature", UNKNOWN_REPO)

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 1
    assert "nowhere" in out
    assert path.read_bytes() == UNKNOWN_REPO


def test_a_change_refused_among_three_does_not_stop_the_other_two(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    alpha = write_change(run, "alpha", OLD)
    beta = write_change(run, "beta", UNKNOWN_REPO)
    gamma = write_change(run, "gamma", OLD)

    code, out = run_tags(capsys, "--fix", "--all")

    assert code == 1
    assert alpha.read_bytes() == NEW
    assert gamma.read_bytes() == NEW
    assert beta.read_bytes() == UNKNOWN_REPO
    assert "beta" in out
    assert "nowhere" in out


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write a read-only file")
def test_a_read_only_file_is_refused_naming_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    path = write_change(run, "feature", OLD)
    path.chmod(0o444)

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 1
    assert "read-only" in line_about(out, "feature")
    assert path.read_bytes() == OLD


def test_a_file_that_is_not_valid_text_is_refused_naming_the_reason(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    broken = b"\xff\xfe" + OLD
    path = write_change(run, "feature", broken)

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 1
    assert "not valid text" in line_about(out, "feature")
    assert path.read_bytes() == broken


def test_a_rewrite_that_parses_differently_is_refused_and_unwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    original = one_group_text(OLD_UNIT_TEST_TAG)
    path = write_change(run, "feature", original)
    reads = work_graph.new_spelling

    def misreads_the_new_tag(place, name):
        """The parser reading the new unit-test tag as another kind: a rewrite whose parse
        differs in kind from the original's."""
        return "e2e-test" if name == "unit-test" else reads(place, name)

    monkeypatch.setattr(work_graph, "new_spelling", misreads_the_new_tag)

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 1
    assert "feature" in out
    assert path.read_bytes() == original


def test_the_write_is_atomic_so_a_failure_part_way_leaves_the_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    run = planning(tmp_path, monkeypatch)
    path = write_change(run, "feature", OLD)

    def disk_full(source, target):
        raise OSError("no space left on device")

    monkeypatch.setattr(os, "replace", disk_full)

    code, out = run_tags(capsys, "--fix", "feature")

    assert code == 1
    assert "feature" in out
    assert path.read_bytes() == OLD
    assert sorted(p.name for p in path.parent.iterdir()) == ["tasks.md", "tasks.md.lock"]
