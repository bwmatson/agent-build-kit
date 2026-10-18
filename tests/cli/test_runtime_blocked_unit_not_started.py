"""A unit parked for a blocked runtime is never started by a tick: it waits to be released,
not to be built again (spec: e2e-runtime-parking)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.vocabulary import WaitReason
from tests.cli.test_wait_reasons import (  # noqa: F401
    installation,
    isolated,
    waits_of,
)
from tests.factories import new_unit
from tests.parked_split_support import installation as split_installation


def parked(store: UnitStore, inst: Installation) -> None:
    store.upsert([new_unit("second/1")])
    store.set_state(
        "second/1", PLANNED, note="e2e-test tests of acp did not run", cause=Cause.SPLIT_HELD
    )
    store.set_parked("second/1", ["acp"], "sha-1", "first run")


def test_a_round_does_not_start_a_unit_parked_for_a_runtime(tmp_path: Path) -> None:
    inst = split_installation(tmp_path)
    store = UnitStore(tmp_path / "units.json")
    parked(store, inst)

    ready = cli.run_round(inst, store, building=(), only=frozenset(), submit=True)

    assert [unit.id for unit in ready] == []
    assert store.get("second/1").parked_splits == ["acp"]


def test_a_unit_parked_for_a_runtime_reads_as_blocked(tmp_path: Path) -> None:
    waits = waits_of(tmp_path, parked)

    assert waits["second/1"].reason is WaitReason.BLOCKED
