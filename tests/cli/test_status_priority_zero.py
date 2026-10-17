"""`abk status` names priority 0 in its priority list and its ready queue."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.conftest import ready_queue, status_lines
from tests.factories import stored_unit


def test_status_lists_a_priority_zero_unit_first_with_its_reason_and_only_then(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "zero").mkdir()
    (tmp_path / "normal").mkdir()
    others = [
        stored_unit("plain/1", change="plain"),
        stored_unit("one/1", change="one", priority=1),
    ]

    lines = status_lines(
        tmp_path / "zero",
        monkeypatch,
        capsys,
        [*others, stored_unit("zero/1", change="zero", priority=0)],
    )
    normal = status_lines(tmp_path / "normal", monkeypatch, capsys, [stored_unit("plain/1")])

    assert any("priority:" in line and "zero/1 0" in line for line in lines)
    assert ready_queue(lines)[0] == "1. zero/1 (app) — priority 0"
    assert not any("priority:" in line for line in normal)


def test_status_says_a_prerequisite_of_a_priority_zero_unit_takes_priority_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [
            stored_unit("older/1", change="older", priority=1),
            stored_unit("base/1", change="base"),
            stored_unit("zero/1", change="zero", priority=0, depends_on=("base/1",)),
        ],
    )

    assert ready_queue(lines)[0] == "1. base/1 (app) — priority 0, from zero/1"
