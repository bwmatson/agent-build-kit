"""`abk status` shows a promoted unit's effective priority and the unit that gave it.

The ready queue and the `priority:` line carry the note `priority_note` makes; a unit at the
normal priority with nothing behind it appears in neither with a priority.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.conftest import make_installation, ready_queue, run_status
from tests.factories import stored_unit


def status_of_promoted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> list[str]:
    """`base/1` promoted to 1 by `fix/1`, `held/1` at 3 covered by a waiter without a
    promotion, and `plain/1` at 3 with nothing behind it."""
    inst = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit("base/1", change="base"),
            stored_unit("fix/1", change="fix", priority=1, depends_on=("base/1",)),
            stored_unit("held/1", change="held"),
            stored_unit("also/1", change="also", priority=1, depends_on=("held/1",)),
            stored_unit("plain/1", change="plain"),
        ]
    )
    store.set_promotion("base/1", 1, "fix/1")
    return run_status(inst, monkeypatch, capsys)


def test_the_ready_queue_line_of_a_promoted_unit_names_the_unit_that_promoted_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_of_promoted(tmp_path, monkeypatch, capsys)

    queue = ready_queue(lines)
    assert next(line for line in queue if "base/1" in line).endswith(
        "priority 1, promoted from fix/1"
    )
    assert next(line for line in queue if "held/1" in line).endswith("priority 1, from also/1")


def test_the_priority_line_lists_a_promoted_unit_with_its_source_and_not_a_normal_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_of_promoted(tmp_path, monkeypatch, capsys)

    summary = next(line for line in lines if "priority:" in line)
    assert "base/1" in summary and "promoted from fix/1" in summary
    assert "plain/1" not in summary


def test_a_unit_at_normal_priority_with_nothing_behind_it_has_no_priority_in_the_queue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_of_promoted(tmp_path, monkeypatch, capsys)

    plain = next(line for line in ready_queue(lines) if "plain/1" in line)
    assert "priority" not in plain
    assert "promoted from" in next(line for line in lines if "priority:" in line)


def test_a_started_promoted_unit_is_listed_with_its_source_in_the_priority_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit("base/1", change="base"),
            stored_unit("fix/1", change="fix", priority=1, depends_on=("base/1",)),
        ]
    )
    store.set_promotion("base/1", 1, "fix/1")
    store.set_state("base/1", RUNNING, branch="spec/base/1")

    lines = run_status(inst, monkeypatch, capsys)

    summary = next(line for line in lines if "priority:" in line)
    assert "base/1 priority 1, promoted from fix/1" in summary


def test_a_started_unit_a_more_urgent_waiter_covers_is_listed_with_that_waiter(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    inst = make_installation(
        tmp_path, planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees"))
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert(
        [
            stored_unit("base/1", change="base"),
            stored_unit("fix/1", change="fix", priority=1, depends_on=("base/1",)),
        ]
    )
    store.set_state("base/1", RUNNING, branch="spec/base/1")

    lines = run_status(inst, monkeypatch, capsys)

    summary = next(line for line in lines if "priority:" in line)
    assert "base/1 priority 1, from fix/1" in summary
