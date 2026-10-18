"""A unit put back again and again with the same cause is named as looping, and only named.

The tick logs it once, `abk status` lists it under `looping:`, and the ready queue marks it
`(looping)`; the scheduler admits it as it would without the count.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW
from tests import fake_clock
from tests.bounce_support import bounce, bounce_times
from tests.conftest import make_installation, ready_queue, run_status
from tests.factories import unit

NOTE = "the base moved again"
LOOPING = "is looping: put back to planned 3 times in 120s by base_changed"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> fake_clock.FakeClock:
    return fake_clock.install(monkeypatch)


def test_status_lists_a_planned_unit_at_the_limit_under_looping(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clock: fake_clock.FakeClock,
) -> None:
    inst = make_installation(tmp_path)
    store = cli.store_for(inst)
    store.upsert([unit("a/1"), unit("a/2"), unit("a/3")], change="a")
    bounce_times(store, "a/1", Cause.BASE_CHANGED, clock, 3, note=NOTE)
    bounce_times(store, "a/2", Cause.BASE_CHANGED, clock, 2, note=NOTE)
    bounce_times(store, "a/3", Cause.BASE_CHANGED, clock, 3, note=NOTE)
    store.set_state("a/3", IN_REVIEW, pr=3, branch="spec/a/3")

    lines = run_status(inst, monkeypatch, capsys)

    looping = [line for line in lines if "looping:" in line]
    assert len(looping) == 1
    assert "a/1" in looping[0]
    assert "(app)" in looping[0]
    assert "3 times in a row" in looping[0]
    assert "base_changed" in looping[0]
    assert NOTE in looping[0]


def test_status_lists_nothing_once_the_count_is_zeroed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clock: fake_clock.FakeClock,
) -> None:
    inst = make_installation(tmp_path)
    store = cli.store_for(inst)
    store.upsert([unit("a/1")], change="a")
    bounce_times(store, "a/1", Cause.BASE_CHANGED, clock, 3, note=NOTE)
    assert any("looping:" in line for line in run_status(inst, monkeypatch, capsys))

    bounce(store, "a/1", Cause.BASE_CHANGED, clock, seconds=600)

    assert not any("looping:" in line for line in run_status(inst, monkeypatch, capsys))


def test_the_ready_queue_marks_a_looping_unit_and_still_admits_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    clock: fake_clock.FakeClock,
) -> None:
    inst = make_installation(tmp_path)
    store = cli.store_for(inst)
    store.upsert([unit("a/1"), unit("b/1", change="b")])
    bounce_times(store, "a/1", Cause.BASE_CHANGED, clock, 3, note=NOTE)

    queue = ready_queue(run_status(inst, monkeypatch, capsys))

    marked = [line for line in queue if " a/1 " in line]
    assert len(marked) == 1
    assert marked[0].endswith("(looping)")
    assert any(" b/1 " in line and "(looping)" not in line for line in queue)


def test_the_tick_logs_a_looping_unit_once(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], clock: fake_clock.FakeClock
) -> None:
    store = cli.store_for(make_installation(tmp_path))
    store.upsert([unit("a/1")], change="a")
    capsys.readouterr()

    bounce_times(store, "a/1", Cause.BASE_CHANGED, clock, 3, note=NOTE)
    first = [line for line in capsys.readouterr().out.splitlines() if LOOPING in line]
    bounce(store, "a/1", Cause.BASE_CHANGED, clock, note=NOTE)
    again = [line for line in capsys.readouterr().out.splitlines() if "is looping" in line]

    assert len(first) == 1
    assert "a/1" in first[0]
    assert NOTE in first[0]
    assert again == []
