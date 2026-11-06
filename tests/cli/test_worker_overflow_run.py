"""A comment rework a full resolution lane passed over runs in a worker process as the same
resolution run: `abk worker build` starts it as a moved-base run, as the tick's own worker thread
does, and not as a build that would skip a unit still in review (spec: resolution-lane, a full
lane overflows into the ordinary workers)."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli import worker as worker_cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.units import IN_REVIEW
from tests.emergency_lane_support import build
from tests.lane_run_slots import as_owed_comment
from tests.tick_pass import isolate, workspace


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    isolate(monkeypatch)
    return workspace(tmp_path)


def run_worker(inst: Installation, monkeypatch: pytest.MonkeyPatch, unit_id: str) -> dict[str, Any]:
    """The keyword arguments `abk worker build` gives `build_unit` for the unit."""
    given: dict[str, Any] = {}

    def fake_build(inst: Installation, unit: Any, **kwargs: Any) -> bool:
        given.update(kwargs)
        return True

    monkeypatch.setattr(worker_cli, "build_unit", fake_build)
    assert worker_cli.cmd_worker_build(argparse.Namespace(unit=unit_id), inst) == 0
    return given


def test_the_worker_runs_an_owed_comment_rework_as_a_moved_base_run(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = cli.store_for(inst)
    unit, _ = build("c2/1", IN_REVIEW)
    store.upsert([unit])
    as_owed_comment(store, "c2/1")

    assert run_worker(inst, monkeypatch, "c2/1")["moved_base_run"] is True


def test_the_worker_runs_any_other_unit_as_a_build(
    inst: Installation, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = cli.store_for(inst)
    unit, _ = build("b1/1", IN_REVIEW)
    store.upsert([unit])

    assert run_worker(inst, monkeypatch, "b1/1")["moved_base_run"] is False
