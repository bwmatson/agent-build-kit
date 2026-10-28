"""A tick has work for a settling unit: only a poll sees its checks complete
(spec: merged-waits-for-ci)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import MERGED, SETTLING
from tests.conftest import make_installation
from tests.factories import stored_unit


def work_for(tmp_path: Path, state) -> bool:
    inst = make_installation(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit("feature/1")])
    store.set_state("feature/1", state, pr=3, branch="spec/feature/1")
    return cli.has_work(inst, store)


def test_a_store_holding_only_a_settling_unit_has_work(tmp_path: Path) -> None:
    assert work_for(tmp_path, SETTLING)


def test_a_store_holding_only_a_merged_unit_has_none(tmp_path: Path) -> None:
    assert not work_for(tmp_path, MERGED)
