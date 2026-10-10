"""`abk status` shows each unit's priority and the order the ready queue starts in."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.units import RUNNING
from tests.conftest import status_lines
from tests.factories import stored_unit

PRIORITY = re.compile(r"priority 1|P1")


def queue_after_heading(lines: list[str]) -> list[str]:
    heading = next(i for i, line in enumerate(lines) if "ready queue" in line.lower())
    return lines[heading + 1 :]


def test_status_marks_units_whose_priority_is_not_normal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [
            stored_unit("fix/1", change="fix", priority=1),
            stored_unit("plain/1", change="plain"),
            stored_unit("later/1", change="later", priority=5),
        ],
    )

    summary = next(line for line in lines if "priority:" in line)
    assert "fix/1 1" in summary
    assert "later/1 5" in summary
    assert "plain/1" not in summary
    assert not any("plain/1" in line and re.search(r"priority \d|P\d", line) for line in lines)


def test_status_lists_the_ready_queue_in_the_order_the_scheduler_chose(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [
            stored_unit("first/1", change="first"),
            stored_unit("second/1", change="second"),
            stored_unit("urgent/1", change="urgent", priority=1),
        ],
    )

    order = [
        unit_id
        for line in queue_after_heading(lines)
        for unit_id in ("first/1", "second/1", "urgent/1")
        if unit_id in line
    ]
    assert order == ["urgent/1", "first/1", "second/1"]


def test_status_says_why_a_prerequisite_is_where_it_is(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [
            stored_unit("older/1", change="older"),
            stored_unit("base/1", change="base"),
            stored_unit("fix/1", change="fix", priority=1, depends_on=("base/1",)),
        ],
    )

    queued = queue_after_heading(lines)
    base = next(i for i, line in enumerate(queued) if "base/1" in line)
    older = next(i for i, line in enumerate(queued) if "older/1" in line)
    assert PRIORITY.search(queued[base])
    assert "fix/1" in queued[base], "an inherited priority names the unit it comes from"
    assert base < older


def test_status_shows_the_priority_of_a_unit_that_is_not_ready(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [
            stored_unit("fix/1", change="fix", priority=1, state=RUNNING),
            stored_unit("plain/1", change="plain"),
        ],
    )

    assert not any("fix/1" in line for line in queue_after_heading(lines))
    summary = next(line for line in lines if "priority:" in line)
    assert "fix/1 1" in summary


def test_a_unit_held_by_a_lease_gives_its_prerequisite_no_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    Leases(lease_dir(tmp_path)).take("fix/1", "tab:a")
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [
            stored_unit("older/1", change="older"),
            stored_unit("base/1", change="base"),
            stored_unit("fix/1", change="fix", priority=1, depends_on=("base/1",)),
        ],
    )

    queued = queue_after_heading(lines)
    assert queued[0].split("older/1")[0].endswith("1. ")
    assert next(line for line in queued if "base/1" in line).endswith("planned order")
