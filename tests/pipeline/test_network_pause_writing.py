"""Parking a unit for the network writes the pause that stops agent runs; nothing else does.

The marker is the pipeline's one `paused.json`, of kind `network`, with a reason naming the
unit. A second parking while it stands leaves its time alone; a parking for the model service
writes none; and a unit that runs while it stands still fails for a reason of its own.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.pipeline.network_probe import Reachability
from agent_build_kit.pipeline.units import FAILED, PLANNED
from tests.pipeline.test_network_outage_parking import (
    UNIT,
    Probe,
    build_once,
    fresh_store,
    outage,
    raises_in_implement,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture
def probe(monkeypatch: pytest.MonkeyPatch) -> Probe:
    return Probe(monkeypatch)


def marker(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "paused.json").read_text())


@pytest.mark.parametrize(
    "reached", [None, Reachability(api=False, control=False)], ids=["strong", "weak-both-down"]
)
def test_parking_for_the_network_writes_a_network_pause_naming_the_unit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    probe: Probe,
    reached: Reachability | None,
) -> None:
    if reached is not None:
        probe.answer = reached

    build_once(
        tmp_path,
        monkeypatch,
        fresh_store(tmp_path),
        run=raises_in_implement(outage("weak" if reached else "strong")),
    )

    written = marker(tmp_path)
    assert written["kind"] == "network"
    assert UNIT in written["reason"]
    assert datetime.fromisoformat(written["until"]) > datetime.now(UTC)


def test_a_second_parking_while_the_pause_stands_does_not_replace_its_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    store = fresh_store(tmp_path)
    build_once(tmp_path, monkeypatch, store, run=raises_in_implement(outage("strong")))
    first = marker(tmp_path)

    build_once(tmp_path, monkeypatch, store, run=raises_in_implement(outage("strong")))

    assert store.get(UNIT).parked_attempts == 2
    assert marker(tmp_path)["until"] == first["until"]


def test_parking_for_the_model_service_writes_no_pause(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    store = fresh_store(tmp_path)
    build_once(tmp_path, monkeypatch, store, run=raises_in_implement(outage("strong")))
    assert marker(tmp_path)["kind"] == "network"
    (tmp_path / "paused.json").unlink()
    probe.answer = Reachability(api=False, control=True)

    build_once(tmp_path, monkeypatch, store, run=raises_in_implement(outage("weak")))

    assert store.get(UNIT).cause == "service_unavailable"
    assert not (tmp_path / "paused.json").exists()


def test_a_unit_that_runs_while_the_pause_stands_and_fails_for_its_own_reason_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, probe: Probe
) -> None:
    store = fresh_store(tmp_path)
    build_once(tmp_path, monkeypatch, store, run=raises_in_implement(outage("strong")))
    assert marker(tmp_path)["kind"] == "network"
    assert store.get(UNIT).state == PLANNED

    build_once(
        tmp_path,
        monkeypatch,
        store,
        run=raises_in_implement(RuntimeError("the build script exited 2")),
    )

    failed = store.get(UNIT)
    assert (failed.state, failed.cause) == (FAILED, "failed")
    assert "exited 2" in failed.note
    assert marker(tmp_path)["kind"] == "network", "a failure of its own does not end the outage"
