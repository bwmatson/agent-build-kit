"""The queue line and the status leave a failed unit that waits out of the units
holding places, count it apart, and say what it waits on."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW, PLANNED, RUNNING
from tests.conftest import status_lines
from tests.factories import new_unit


def full_queue() -> list[StoredUnit]:
    """Two places held (a unit in review and a running prerequisite), a failed
    unit that waits on the prerequisite and a failed one that waits on nothing."""
    return [
        new_unit("rev/1", state=IN_REVIEW, pr=11),
        new_unit("base/1", state=RUNNING),
        new_unit("wait/1", state=FAILED, depends_on=("base/1",)),
        new_unit("plain/1", state=FAILED),
    ]


def test_the_queue_line_leaves_a_waiting_failed_unit_out_and_says_how_many_are_not_counted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(tmp_path, monkeypatch, capsys, full_queue(), limit=2)

    queue = next(line for line in lines if "queue is full" in line)
    assert "3 units in progress" in queue
    assert "(1 failed, 1 in review, 1 running)" in queue
    assert queue.endswith("1 failed waiting not counted")


def test_the_failed_waiting_count_follows_the_blocked_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    units = [
        *full_queue(),
        new_unit("blocked/1", state=PLANNED, branch="spec/blocked/1", depends_on=("base/1",)),
    ]

    lines = status_lines(tmp_path, monkeypatch, capsys, units, limit=2)

    queue = next(line for line in lines if "queue is full" in line)
    assert "1 blocked not counted; 1 failed waiting not counted" in queue


def test_the_status_says_what_a_waiting_failed_unit_waits_on_and_keeps_its_failed_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(tmp_path, monkeypatch, capsys, full_queue(), limit=2)

    waiting = [line for line in lines if "failed, waiting on" in line]
    assert len(waiting) == 1
    assert "wait/1" in waiting[0]
    assert "base/1" in waiting[0]
    assert any("failed: wait/1" in line for line in lines)
    assert any("failed: plain/1" in line for line in lines)
