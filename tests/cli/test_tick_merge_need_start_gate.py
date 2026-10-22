"""The start gate holds a unit whose merge edge is unmet (spec: needs-can-wait-for-a-merge): it is
parked `planned`/`gated` with the wait named and holds no place, a person's requeue of a failed
unit waits for the merge to be loaded, and a unit already running is not stopped."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED, IN_REVIEW, MERGED, PLANNED, RUNNING, blocked
from agent_build_kit.pipeline.usage_guard import Decision
from tests.conftest import make_installation
from tests.factories import commit, git, new_unit
from tests.kit_checkout import kit_at

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    made = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        project_limits={"max_concurrent_stacks": 2, "max_units_in_progress": 50},
    )
    (made.root / "abk.yaml").write_text(dump(made.config))
    monkeypatch.chdir(made.root)
    return made


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    return UnitStore(inst.state_dir / "units.json")


class Thread:
    """What `resume_thread` is handed: the unit has a saved thread, and every event delivered
    to it is recorded."""

    def __init__(self, patch: pytest.MonkeyPatch) -> None:
        self.delivered: list[dict[str, Any]] = []
        patch.setattr(cli, "has_thread", lambda inst, unit_id: True)
        patch.setattr(cli, "resume_thread", self.resume)

    def resume(self, inst: Installation, unit: Any, kind: str, **kwargs: Any) -> None:
        self.delivered.append({"unit": unit.id, "kind": kind, **kwargs})


@pytest.fixture
def thread(monkeypatch: pytest.MonkeyPatch) -> Thread:
    return Thread(monkeypatch)


def tick(inst: Installation) -> int:
    return cli.cmd_tick(argparse.Namespace(dry_run=False), inst)


def merge_need(store: UnitStore, uid: str = "feature/1") -> None:
    """`uid` depends on `dep/1`, in the same repository, with `merged` on its `Needs:` line."""
    store.set_needs(uid, ("dep/1",))
    store.set_merge_needs(uid, ("dep/1",))


def test_a_unit_sent_back_with_an_unmet_merge_edge_is_gated_with_the_wait_named(
    store: UnitStore,
) -> None:
    store.upsert([new_unit("dep/1"), new_unit("feature/1", depends_on=("dep/1",))])
    store.set_state("dep/1", IN_REVIEW, pr=3)
    store.set_state("feature/1", PLANNED, note="reworking", cause=Cause.REWORK)
    merge_need(store)

    cli.gate_sent_back(store)

    gated = store.get("feature/1")
    assert (gated.state, gated.cause) == (PLANNED, Cause.GATED)
    assert "dep group 1" in gated.note
    assert "to merge" in gated.note
    assert blocked(gated, store.all()), "it holds no place while it waits"


def test_a_running_unit_that_gains_a_merge_needs_is_not_stopped(store: UnitStore) -> None:
    store.upsert(
        [
            new_unit("dep/1"),
            new_unit("feature/1", depends_on=("dep/1",)),
            new_unit("other/1", depends_on=("dep/1",)),
        ]
    )
    store.set_state("dep/1", IN_REVIEW, pr=3)
    store.set_state("feature/1", RUNNING, branch="spec/feature/1")
    store.set_state("other/1", PLANNED, note="reworking", cause=Cause.REWORK)
    merge_need(store)
    merge_need(store, "other/1")

    cli.gate_sent_back(store)

    assert store.get("other/1").cause is Cause.GATED, "the gate does act on a unit that is planned"
    running = store.get("feature/1")
    assert (running.state, running.cause) == (RUNNING, None)


def test_a_failed_unit_requeued_by_a_person_waits_for_the_merge_to_be_loaded(
    inst: Installation,
    store: UnitStore,
    thread: Thread,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    head = kit_at(inst.checkouts["app"], monkeypatch)
    kit = inst.checkouts["app"]
    git(kit, "checkout", "-q", "-b", "fix")
    fix = commit(kit, "fix.txt")
    git(kit, "checkout", "-q", "main")
    store.upsert([new_unit("dep/1"), new_unit("feature/1", depends_on=("dep/1",))])
    store.set_state("dep/1", IN_REVIEW, pr=3)
    store.set_state("feature/1", FAILED, branch="spec/feature/1")
    store.set_needs("feature/1", ("dep/1",))

    assert main(["requeue", "feature/1"]) == 0

    after = store.get("feature/1")
    assert (after.state, after.cause) == (PLANNED, Cause.GATED), "a plain parent in review"
    assert thread.delivered == []

    store.set_state("dep/1", MERGED, pr=3)
    store.set_merge_record("dep/1", merge_sha=fix, merged_tick=0)
    assert tick(inst) == 0
    assert thread.delivered == [], f"the tick's head {head} does not have the merge yet"
    assert store.get("feature/1").cause is Cause.GATED

    git(kit, "merge", "-q", "--ff-only", "fix")
    assert tick(inst) == 0
    assert [call["unit"] for call in thread.delivered] == ["feature/1"]
