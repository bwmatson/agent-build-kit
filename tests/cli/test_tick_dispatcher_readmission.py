"""What lets a dispatcher admit a unit again (spec: unit-workers): a worker's finish and a wake free
a slot with no five-minute round; a dependent on a merged kit parent starts when the kit checkout's
head contains the merge commit, whatever the tick number; a unit sent back is planned again, and
more sends back than the rebuild budget in its window hold it for a person."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import wake
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED, PLANNED
from tests.dispatcher_support import FakeSpawner, install_spawner, processes_workspace
from tests.factories import commit, git
from tests.kit_checkout import kit_at
from tests.tick_pass import Builder, install_builder, isolate, stored, tick, warm_unit_graphs

pytestmark = pytest.mark.usefixtures("scripted_engine")

REBUILD_BUDGET = 6


@pytest.fixture(autouse=True)
def warmed(tmp_path: Path) -> None:
    warm_unit_graphs(tmp_path)


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    isolate(monkeypatch)


@pytest.fixture
def builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    return install_builder(tmp_path, monkeypatch)


@pytest.fixture
def spawner(monkeypatch: pytest.MonkeyPatch) -> FakeSpawner:
    return install_spawner(monkeypatch)


def finish(builder: Builder, inst: Installation, unit: str) -> None:
    """What a worker leaves when it ends at review: its marker gone, the unit in review, the
    wake file touched."""
    builder.store.set_starting(unit, None)
    builder.store.set_state(unit, IN_REVIEW, pr=1)
    wake.touch(inst.state_dir)


def test_a_workers_finish_and_a_wake_let_the_next_dispatcher_admit_the_waiting_unit(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner
) -> None:
    inst = processes_workspace(tmp_path, max_concurrent=1)
    builder.store.upsert([stored("a/1"), stored("b/1")])

    assert tick(inst) == 0
    assert tick(inst) == 0
    assert len(spawner.calls) == 1, "the one slot is held until its worker finishes"

    finish(builder, inst, spawner.units[0])

    assert tick(inst) == 0
    assert sorted(spawner.units) == ["a/1", "b/1"]


def test_a_dependent_on_a_merged_kit_parent_starts_when_the_kit_head_has_the_merge(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = processes_workspace(tmp_path, max_concurrent=2)
    (inst.root / "abk.yaml").write_text(dump(inst.config))
    monkeypatch.chdir(inst.root)
    kit = inst.checkouts["app"]
    kit_at(kit, monkeypatch)
    git(kit, "checkout", "-q", "-b", "fix")
    fix = commit(kit, "fix.txt")
    git(kit, "checkout", "-q", "main")
    builder.store.upsert([stored("dep/1"), stored("feature/1", depends_on=("dep/1",))])
    builder.store.set_state("dep/1", MERGED, pr=3)
    builder.store.set_merge_record("dep/1", merge_sha=fix, merged_tick=None)
    builder.store.set_needs("feature/1", ("dep/1",))
    builder.store.set_merge_needs("feature/1", ("dep/1",))

    assert tick(inst) == 0
    assert spawner.calls == [], "the kit head does not contain the merge yet"
    assert builder.store.get("feature/1").state == PLANNED

    git(kit, "merge", "-q", "--ff-only", "fix")

    assert tick(inst) == 0
    assert spawner.units == ["feature/1"]


def test_a_unit_sent_back_is_planned_again_and_over_the_rebuild_budget_is_held(
    tmp_path: Path, builder: Builder, spawner: FakeSpawner
) -> None:
    inst = processes_workspace(tmp_path)
    builder.store.upsert([stored("a/1")])

    for round_ in range(REBUILD_BUDGET):
        builder.store.set_state("a/1", PLANNED, note="reworking", cause=Cause.REWORK)
        assert tick(inst) == 0
        assert len(spawner.calls) == round_ + 1, "within the budget a sent-back unit is rebuilt"
        finish(builder, inst, "a/1")

    builder.store.set_state("a/1", PLANNED, note="reworking", cause=Cause.REWORK)
    assert tick(inst) == 0

    assert len(spawner.calls) == REBUILD_BUDGET
    held = builder.store.get("a/1")
    assert (held.state, held.cause) == (HELD, Cause.NEEDS_HUMAN)
