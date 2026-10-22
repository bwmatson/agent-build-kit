"""A runner given no fixers changes nothing (spec: fixers-run-before-commits)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.stack_runner import FixResult
from agent_build_kit.pipeline.unit_store import UnitStore
from tests.runner_fakes import Recorder, make_runner


def test_a_runner_built_without_fixers_reports_nothing_changed(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    runner = make_runner(store, Recorder(store), tmp_path)

    assert runner.run_fixers(cwd=tmp_path) == FixResult()
