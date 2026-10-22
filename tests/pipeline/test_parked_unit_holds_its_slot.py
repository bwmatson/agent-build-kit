"""A started unit parked before its first agent step holds its slot, and the status says it is
paused (spec: capacity-checks, a parked started unit holds its slot).

`prepare` records the unit's branch and stores it `running`; a pause then parks it with no run
holding its branch. The slot counts are pinned in `test_parked_unit_counts.py`; these are what
the full-queue line says of such units.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.pipeline.pause import PAUSE_MARKER, pause_until
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import FAILED, RUNNING
from tests.conftest import status_lines
from tests.factories import new_unit
from tests.pipeline.test_slots_per_account import kit, repos


def park_two(tmp_path: Path, account: str | None = None) -> Callable[[UnitStore], None]:
    """Two units that ran `prepare` and no more, and a usage pause of their account (the default
    account's unless one is named) in force that parks them."""
    marker = tmp_path / (PAUSE_MARKER if account is None else f"paused.{account}.json")

    def record(store: UnitStore) -> None:
        store.upsert([new_unit(f"parked{n}/1") for n in range(2)])
        for n in range(2):
            store.set_state(f"parked{n}/1", RUNNING, branch=f"spec/parked{n}/1")
        pause_until(
            None, reason="weekly usage at 93% (threshold 93%)", marker=marker, account=account
        )

    return record


def full_line(lines: list[str]) -> str:
    [line] = [line for line in lines if "queue is full" in line]
    return line


def test_the_full_queue_line_names_parked_started_units_paused_not_running(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [new_unit("fresh/1")],
        limit=2,
        record=park_two(tmp_path),
    )

    line = full_line(lines)
    assert "2 units in progress, limit 2" in line
    assert "2 paused" in line
    assert "running" not in line


def test_the_full_queue_line_of_an_account_names_its_parked_units_paused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    lines = status_lines(
        tmp_path,
        monkeypatch,
        capsys,
        [new_unit("fresh/1")],
        repos=repos(tmp_path, {"app": "kit"}),
        runtimes={"claude_code": {"accounts": kit(tmp_path, max_units_in_progress=2)}},
        record=park_two(tmp_path, account="kit"),
    )

    line = full_line(lines)
    assert "account kit" in line
    assert "2 paused" in line
    assert "running" not in line


def test_parked_units_are_named_paused_beside_other_states_in_the_same_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    parked = park_two(tmp_path)

    def with_failed(store: UnitStore) -> None:
        parked(store)
        store.upsert([new_unit("broke/1")])
        store.set_state("broke/1", FAILED, note="broke", branch="spec/broke/1")

    lines = status_lines(tmp_path, monkeypatch, capsys, limit=3, record=with_failed)

    line = full_line(lines)
    assert "1 failed" in line
    assert "2 paused" in line
