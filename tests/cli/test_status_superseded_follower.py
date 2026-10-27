"""`abk status` does not show an acceptance unit waiting on the closed original of a split
(spec: acceptance-follow)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED, PLANNED, UnitState
from tests.conftest import status_lines
from tests.pipeline.test_earlier_units_skip_superseded import FOLLOWER, change

ORIGINAL = re.compile(r"feature/4(?![-\w])")


def lines_of(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    second: UnitState,
) -> list[str]:
    units = change(second=second)

    def record(store: UnitStore) -> None:
        store.import_units(units)
        for unit in units:
            store.set_state(unit.id, unit.state)

    return status_lines(tmp_path, monkeypatch, capsys, record=record)


def test_merged_pieces_leave_the_follower_not_waiting_on_the_closed_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = lines_of(tmp_path, monkeypatch, capsys, MERGED)

    assert not [line for line in lines if FOLLOWER in line and ORIGINAL.search(line)]


def test_a_planned_piece_is_what_the_follower_waits_on(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = lines_of(tmp_path, monkeypatch, capsys, PLANNED)

    waiting = [line for line in lines if FOLLOWER in line and "feature/4-s2" in line]
    assert waiting
    assert not [line for line in lines if FOLLOWER in line and ORIGINAL.search(line)]
