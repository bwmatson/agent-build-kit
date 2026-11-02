"""The restack at the start of a run (`prepare`) and the one before the push (`verify_base`)
each write a `restack` line of the usage ledger (spec: restack-points, each restack decision
is recorded and summarised). `restack_onto` is faked at its edge, as in the build path's
tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_build_kit.installation import Installation
from tests.factories import unit
from tests.graph.test_build_path import build, fresh, restacked


def restack_lines(workspace: Installation) -> list[dict]:
    path = workspace.state_dir / "usage-ledger.jsonl"
    lines = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
    return [line for line in lines if line.get("kind") == "restack"]


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
        if len(calls) != 2:
            return None
        recorder.made += 1
        recorder.store.record_approval(unit().id, recorder.head(tmp_path))
        return restacked(old_base="beforepush")

    build(tmp_path, recorder, restack_onto=restack)

    (line,) = [line for line in restack_lines(workspace) if line["point"] == "before_pr"]
    assert (line["moved"], line["moved_from"], line["outcome"]) == (True, "beforepush", "clean")
    assert line["unit"] == unit().id


def test_a_conflict_before_the_push_is_recorded_as_before_pr_with_the_outcome_conflict(
    tmp_path: Path, workspace: Installation
) -> None:
    recorder = fresh(tmp_path)
    recorder.made = 2
    calls: list[int] = []

    def restack(**kw: Any) -> Any:
        calls.append(1)
        if len(calls) == 2:
            return restacked(conflict="CONFLICT in a.py")
        return None

    build(tmp_path, recorder, restack_onto=restack)

    before_pr = [line for line in restack_lines(workspace) if line["point"] == "before_pr"]
    assert before_pr
    assert before_pr[0]["outcome"] == "conflict"
