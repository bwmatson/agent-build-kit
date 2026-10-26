"""A `running` unit nothing holds is checked against its dependencies before it resumes (spec:
resume-gating): an unmet merge edge makes it `planned`/`gated` with the wait text and its thread
kept, and it resumes once the parent has merged. A unit a process holds is left alone."""

from __future__ import annotations

import argparse
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.explain_cmd import cmd_explain
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.loaded_code import TickRecord, write_record
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, PLANNED, RUNNING, ready_units
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.conftest import make_installation, run_status
from tests.factories import stored_unit

PARENT = "dep/1"
CHILD = "feature/1"
WAIT = "waiting for dep group 1 to merge"


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    monkeypatch.setattr(cli, "has_thread", lambda _inst, _uid: True)
    return make_installation(tmp_path, planning={"state_dir": "."})


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    return UnitStore(inst.state_dir / "units.json")


def running_child(store: UnitStore, *, repo: str = "platform", merge: bool = False) -> None:
    """CHILD is `running` with a thread; PARENT, in `repo`, is in review."""
    store.upsert(
        [
            stored_unit(PARENT, change="dep", repo=repo),
            stored_unit(CHILD, change="feature", depends_on=(PARENT,)),
        ]
    )
    store.set_state(PARENT, IN_REVIEW, pr=3, branch=f"spec/{PARENT}")
    store.set_state(CHILD, RUNNING, branch=f"spec/{CHILD}")
    if merge:
        store.set_merge_needs(CHILD, (PARENT,))


def resumable(inst: Installation, store: UnitStore) -> list[str]:
    return [u.id for u in cli.resumable_units(inst, store.all(), only=frozenset())]


def ready(store: UnitStore) -> list[str]:
    return [u.id for u in ready_units(store.all(), max_concurrent=4, depth_cap=9)]


def test_an_unmet_merge_edge_gates_the_unit_and_keeps_its_thread(
    inst: Installation, store: UnitStore
) -> None:
    running_child(store)

    cli.gate_resumable(inst, store)

    gated = store.get(CHILD)
    assert (gated.state, gated.cause) == (PLANNED, Cause.GATED)
    assert WAIT in gated.note
    assert resumable(inst, store) == []


def test_a_needs_line_that_says_merged_gates_a_unit_of_the_same_repo(
    inst: Installation, store: UnitStore
) -> None:
    running_child(store, repo="app", merge=True)

    cli.gate_resumable(inst, store)

    assert (store.get(CHILD).state, store.get(CHILD).cause) == (PLANNED, Cause.GATED)


def test_the_gated_unit_resumes_in_the_round_after_its_parent_has_merged(
    inst: Installation, store: UnitStore
) -> None:
    running_child(store)
    cli.gate_resumable(inst, store)
    assert CHILD not in ready(store)

    store.set_state(PARENT, MERGED, pr=3)
    cli.gate_resumable(inst, store)

    assert store.get(CHILD).state == PLANNED
    assert CHILD in ready(store)


def test_a_merge_the_running_tick_does_not_have_still_holds_the_unit_until_the_next_tick(
    inst: Installation, store: UnitStore
) -> None:
    def tick(number: int) -> None:
        write_record(
            inst.state_dir,
            TickRecord(number=number, started_at=datetime.now(UTC), kit_repo="app"),
        )

    running_child(store)
    store.set_state(PARENT, MERGED, pr=3)
    store.set_merge_record(PARENT, merge_sha="abc", merged_tick=3)
    tick(3)

    cli.gate_resumable(inst, store)

    assert (store.get(CHILD).state, store.get(CHILD).cause) == (PLANNED, Cause.GATED)
    assert CHILD not in ready(store)

    tick(4)
    assert CHILD in ready(store)


def test_a_review_edge_in_the_same_repo_does_not_gate(inst: Installation, store: UnitStore) -> None:
    running_child(store, repo="app")

    cli.gate_resumable(inst, store)

    assert store.get(CHILD).state == RUNNING
    assert resumable(inst, store) == [CHILD]


def test_a_unit_whose_edges_are_met_resumes_as_before(inst: Installation, store: UnitStore) -> None:
    running_child(store)
    store.set_state(PARENT, MERGED, pr=3)

    cli.gate_resumable(inst, store)

    assert store.get(CHILD).state == RUNNING
    assert resumable(inst, store) == [CHILD]


def test_a_unit_whose_branch_lock_is_held_is_not_gated(
    inst: Installation, store: UnitStore
) -> None:
    running_child(store)

    with branch_lock(f"spec/{CHILD}", root=inst.state_dir / "locks"):
        cli.gate_resumable(inst, store)

    assert store.get(CHILD).state == RUNNING


def test_a_unit_with_a_lease_is_not_gated(inst: Installation, store: UnitStore) -> None:
    running_child(store)
    assert Leases(lease_dir(inst.state_dir)).take(CHILD, f"holder-{os.getpid()}")

    cli.gate_resumable(inst, store)

    assert store.get(CHILD).state == RUNNING


def test_a_unit_a_run_is_in_flight_on_is_not_gated(inst: Installation, store: UnitStore) -> None:
    running_child(store)

    cli.gate_resumable(inst, store, spared=(CHILD,))

    assert store.get(CHILD).state == RUNNING


def test_status_and_explain_say_what_a_gated_unit_waits_on(
    inst: Installation,
    store: UnitStore,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    running_child(store)
    cli.gate_resumable(inst, store)

    lines = run_status(inst, monkeypatch, capsys)
    assert any(CHILD in line and WAIT in line for line in lines)

    assert cmd_explain(argparse.Namespace(unit=CHILD, at=None), inst) == 0
    assert WAIT in capsys.readouterr().out
