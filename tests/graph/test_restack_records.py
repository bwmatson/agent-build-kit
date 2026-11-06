"""The restack at the start of a run (`prepare`) and the one before the push (`verify_base`)
each write a `restack` line of the usage ledger (spec: restack-points, each restack decision
is recorded and summarised). `restack_onto` is faked at its edge, as in the build path's
tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import spans
from tests.factories import unit
from tests.fake_clock import install
from tests.graph.test_build_path import build, fresh, restacked
from tests.pipeline.test_restack_record import restack_lines


def test_the_restack_at_the_start_of_a_run_that_moves_the_branch_is_recorded_as_prepare(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2
    calls: list[int] = []

    def restack(**kw: Any) -> Any:
        calls.append(1)
        return restacked(old_base="oldbase") if len(calls) == 1 else None

    build(tmp_path, recorder, restack_onto=restack)

    (first, *_) = [line for line in restack_lines(workspace) if line["point"] == "prepare"]
    assert first["unit"] == unit().id
    assert (first["moved"], first["moved_from"], first["outcome"]) == (True, "oldbase", "clean")


def test_a_restack_that_needed_resolution_records_the_time_the_resolution_took(
    tmp_path: Path, workspace: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = install(monkeypatch)
    recorder = fresh(tmp_path)
    recorder.made = 2
    calls: list[int] = []

    def restack(**kw: Any) -> Any:
        calls.append(1)
        if len(calls) != 1:
            return None
        clock.advance(412.5)
        return restacked(resolved=("a.py",))

    build(tmp_path, recorder, restack_onto=restack)

    (prepare, *_) = [line for line in restack_lines(workspace) if line["point"] == "prepare"]
    assert (prepare["outcome"], prepare["resolution_seconds"]) == ("resolved", 412.5)


def test_a_start_of_run_restack_that_finds_the_base_unmoved_is_recorded_as_not_moved(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2

    build(tmp_path, recorder, restack_onto=lambda **kw: None)

    prepare = [line for line in restack_lines(workspace) if line["point"] == "prepare"]
    assert prepare
    assert all(line["moved"] is False for line in prepare)


def test_a_clean_move_before_the_push_is_recorded_as_before_pr(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2
    calls: list[int] = []

    def restack(**kw: Any) -> Any:
        calls.append(1)
        if len(calls) != 3:
            return None
        recorder.made += 1
        recorder.store.record_approval(unit().id, recorder.head(tmp_path))
        return restacked(old_base="beforepush")

    build(tmp_path, recorder, restack_onto=restack)

    (line,) = [line for line in restack_lines(workspace) if line["point"] == "before_pr"]
    assert (line["moved"], line["moved_from"], line["outcome"]) == (True, "beforepush", "clean")
    assert line["unit"] == unit().id


def test_the_re_test_after_a_clean_move_before_the_push_runs_under_the_point_before_pr(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2
    calls: list[int] = []
    points: list[str] = []

    def restack(**kw: Any) -> Any:
        calls.append(1)
        if len(calls) != 3:
            return None
        recorder.made += 1
        recorder.store.record_approval(unit().id, recorder.head(tmp_path))
        return restacked()

    def unit_test(**kw: Any) -> tuple[bool, str]:
        points.append(spans.restack_point.get())
        return True, ""

    build(tmp_path, recorder, restack_onto=restack, run_unit_test=unit_test)

    assert points == ["", "before_pr"], "only the re-test after the move is under the point"
    assert spans.restack_point.get() == "", "and the point is not left set"


def test_a_move_with_no_re_test_still_counts_the_files_it_brought_in_by_kind(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2
    calls: list[int] = []

    def restack(**kw: Any) -> Any:
        calls.append(1)
        if len(calls) != 1:
            return None
        return restacked(brought_in=("CHANGELOG.md", "docs/a.md", "docs/b.md", "src/c.py"))

    build(tmp_path, recorder, restack_onto=restack, repo_config=RepoConfig(path=tmp_path))

    (prepare, *_) = [line for line in restack_lines(workspace) if line["point"] == "prepare"]
    assert prepare["retest"] == "none"
    assert (prepare["changelog"], prepare["documents"], prepare["code"]) == (1, 2, 1)


def test_a_conflict_before_the_push_is_recorded_as_before_pr_with_the_outcome_conflict(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2
    calls: list[int] = []

    def restack(**kw: Any) -> Any:
        calls.append(1)
        if len(calls) == 3:
            return restacked(conflict="CONFLICT in a.py")
        return None

    build(tmp_path, recorder, restack_onto=restack)

    before_pr = [line for line in restack_lines(workspace) if line["point"] == "before_pr"]
    assert before_pr
    assert before_pr[0]["outcome"] == "conflict"
