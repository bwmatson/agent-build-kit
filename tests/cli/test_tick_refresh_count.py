"""The tick driver's count of refreshes: what a test waits on instead of a fixed sleep."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.conftest import make_installation
from tests.tick_driver import count_refreshes


def test_the_count_reaches_n_after_n_refreshes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    refreshes = count_refreshes(monkeypatch)
    assert refreshes.count == 0

    for _ in range(3):
        cli.poll_all(inst, store=store)

    assert refreshes.count == 3
    refreshes.wait_for(3, timeout=1)


def test_waiting_returns_once_refreshes_on_another_thread_reach_the_number(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    refreshes = count_refreshes(monkeypatch)
    worker = threading.Thread(target=lambda: [cli.poll_all(inst, store=store) for _ in range(2)])

    worker.start()
    refreshes.wait_for(2, timeout=5)
    worker.join(timeout=5)

    assert refreshes.count == 2


def test_waiting_for_more_refreshes_than_ran_times_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = make_installation(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    refreshes = count_refreshes(monkeypatch)
    cli.poll_all(inst, store=store)

    with pytest.raises(TimeoutError):
        refreshes.wait_for(2, timeout=0.05)
