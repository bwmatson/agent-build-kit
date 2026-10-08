"""A `Needs: ... merged` line added after a unit has started still gates it.

The gate is `merge_before` on the unit, recomputed from tasks.md every tick. A
failed or held unit requeued before its prerequisite merges waits as `planned`
with the cause `gated` and is resumed, in the mode it was requeued with, once
the prerequisite lands. A running unit is told, not disturbed, and a merge gate
never makes the dependency the unit's base.
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.cli.pipeline import (
    plan_all,
)  # the real one; the autouse stub patches the module
from agent_build_kit.config import dump
from agent_build_kit.graph.checkpointer import unit_graphs_path
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import (
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    base_of,
)
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.wiring import build_upstream_incomplete
from tests.conftest import make_installation
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

NEEDS = "Needs: dep group 1 merged — it reshapes the runtime\n"


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything around building stubbed: GitHub, the network, planning,
    live verification and the usage window."""
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="plenty"))


@pytest.fixture(autouse=True)
def warm_unit_graphs(tmp_path: Path) -> None:
    with closing(sqlite3.connect(unit_graphs_path(tmp_path))) as conn:
        conn.execute("PRAGMA journal_mode=WAL")


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    made = make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"max_concurrent_stacks": 2, "max_units_in_progress": 50},
    )
    (made.root / "abk.yaml").write_text(dump(made.config))
    monkeypatch.chdir(made.root)
    return made


@pytest.fixture
def store(inst: Installation) -> UnitStore:
    return UnitStore(inst.state_dir / "units.json")


def stored(uid: str, **overrides: Any) -> StoredUnit:
    return stored_unit(uid, change=uid.partition("/")[0], **overrides)


def write_needs(inst: Installation, change: str = "feature", group: int = 1) -> Path:
    folder = inst.root / "openspec" / "changes" / change
    folder.mkdir(parents=True, exist_ok=True)
    tasks = folder / "tasks.md"
    tasks.write_text(
        f"# Tasks\n\n## {group}. [app] [tier1] The work\n\n{NEEDS}\n- [ ] {group}.1 Test: it\n"
    )
    return tasks


def gated_failure(store: UnitStore, *, state=FAILED) -> None:
    """`feature/1` stopped with a thread, then a merge gate on `dep/1` (still in
    review) was written for it."""
    store.upsert(
        [
            stored("dep/1", repo="platform"),
            stored("feature/1", depends_on=("dep/1",), merge_before=("dep/1",)),
        ]
    )
    store.set_state("dep/1", IN_REVIEW, pr=3)
    store.set_state("feature/1", state, branch="spec/feature/1")
    store.set_feedback("feature/1", "tier 2 failed: the dev stack is down")


class Thread:
    """What `resume_thread` is handed: the unit has a saved thread, and every
    event delivered to it is recorded."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.delivered: list[dict[str, Any]] = []
        monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)
        monkeypatch.setattr(cli, "resume_thread", self.resume)

    def resume(self, inst, unit, kind, **kwargs):
        self.delivered.append({"unit": unit.id, "kind": kind, **kwargs})
        return None


@pytest.fixture
def thread(monkeypatch: pytest.MonkeyPatch) -> Thread:
    return Thread(monkeypatch)


class Builder:
    """Stands in for `build_runner`: a build runs its script, then the unit is
    in review."""

    def __init__(self, store: UnitStore) -> None:
        self.store = store
        self.scripts: dict[str, Callable[[], None]] = {}
        self.started: list[str] = []

    def __call__(self, unit, **kwargs):
        return SimpleNamespace(run=lambda unit, *, base, graph: self._run(unit))

    def _run(self, unit) -> RunOutcome:
        self.started.append(unit.id)
        self.store.set_state(unit.id, RUNNING, branch=f"spec/{unit.id}")
        self.scripts.get(unit.id, lambda: None)()
        self.store.set_state(unit.id, IN_REVIEW, pr=len(self.started))
        return RunOutcome(status=RunStatus("open"), detail=f"open {unit.id}", pr=len(self.started))


@pytest.fixture
def builder(store: UnitStore, monkeypatch: pytest.MonkeyPatch) -> Builder:
    fake = Builder(store)
    monkeypatch.setattr(cli, "build_runner", fake)
    return fake


def tick(inst: Installation) -> int:
    return cli.cmd_tick(argparse.Namespace(dry_run=False), inst)


# --- 1.1 a requeue before the gate clears waits ----------------------------------


@pytest.mark.parametrize("state", [FAILED, HELD])
def test_requeue_of_a_gated_unit_leaves_it_planned_and_gated(
    store: UnitStore,
    thread: Thread,
    capsys: pytest.CaptureFixture[str],
    state,
) -> None:
    gated_failure(store, state=state)

    assert main(["requeue", "feature/1"]) == 0

    after = store.get("feature/1")
    assert after.state == PLANNED
    assert after.cause is Cause.GATED
    assert thread.delivered == [], "no event reaches the thread while the gate is unmet"
    assert after.branch == "spec/feature/1"
    assert after.feedback == "tier 2 failed: the dev stack is down"
    out = capsys.readouterr().out
    assert "dep group 1" in out, "the command names the group it waits for"


def test_requeue_of_a_gated_unit_keeps_the_saved_feedback_when_reworking(
    store: UnitStore, thread: Thread
) -> None:
    gated_failure(store)

    assert main(["requeue", "feature/1", "--rework"]) == 0

    after = store.get("feature/1")
    assert (after.state, after.cause) == (PLANNED, Cause.GATED)
    assert after.feedback == "tier 2 failed: the dev stack is down"
    assert thread.delivered == []


def test_requeue_with_the_gate_already_clear_resumes_at_once(
    store: UnitStore, thread: Thread
) -> None:
    gated_failure(store)
    store.set_state("dep/1", MERGED, pr=3)

    assert main(["requeue", "feature/1"]) == 0

    (call,) = thread.delivered
    assert call["kind"] == "requeue"
    assert call["requeue"] is RequeueReason.RESUME
    assert store.get("feature/1").cause is not Cause.GATED


# --- 1.2 the gate clearing resumes the unit in the mode it was requeued with -------


@pytest.mark.parametrize(
    ("flags", "reason"),
    [
        ([], RequeueReason.RESUME),
        (["--rework"], RequeueReason.FROM_FAILURE),
        (["--restart"], RequeueReason.RESTART),
    ],
)
def test_the_pass_resumes_a_gated_unit_in_its_requeued_mode_once_the_gate_clears(
    inst: Installation,
    store: UnitStore,
    thread: Thread,
    builder: Builder,
    flags: list[str],
    reason: RequeueReason,
) -> None:
    gated_failure(store)
    assert main(["requeue", "feature/1", *flags]) == 0

    assert tick(inst) == 0
    assert thread.delivered == [], "still gated: nothing is delivered"
    assert builder.started == []
    assert store.get("feature/1").cause is Cause.GATED

    store.set_state("dep/1", MERGED, pr=3)
    assert tick(inst) == 0

    (call,) = thread.delivered
    assert call["unit"] == "feature/1"
    assert call["kind"] == "requeue"
    assert call["requeue"] is reason


# --- 1.3 a running unit is told, not disturbed -------------------------------------


def test_a_gate_added_to_a_running_unit_changes_neither_its_state_nor_its_base(
    inst: Installation, store: UnitStore
) -> None:
    store.upsert([stored("dep/1"), stored("feature/1")])
    store.set_state("dep/1", IN_REVIEW, pr=3)
    store.set_state("feature/1", RUNNING, branch="spec/feature/1")
    base = base_of(store.get("feature/1"), store.all())
    write_needs(inst)

    cli.link_needs(inst, store=store)

    running = store.get("feature/1")
    assert running.state == RUNNING
    assert running.merge_before == ("dep/1",)
    assert base_of(running, store.all()) == base, "a merge gate is not a stacking edge"


def test_a_gate_added_to_a_running_unit_is_not_an_upstream_change(
    inst: Installation, store: UnitStore
) -> None:
    store.upsert([stored("dep/1"), stored("feature/1")])
    store.set_state("dep/1", PLANNED)
    store.set_state("feature/1", RUNNING, branch="spec/feature/1")
    write_needs(inst)

    cli.link_needs(inst, store=store)

    assert build_upstream_incomplete(store)(store.get("feature/1")) is None


def test_the_wait_is_logged_once_across_repeated_ticks(
    inst: Installation, store: UnitStore, capsys: pytest.CaptureFixture[str]
) -> None:
    store.upsert([stored("dep/1"), stored("feature/1")])
    store.set_state("feature/1", RUNNING, branch="spec/feature/1")
    write_needs(inst)

    for _ in range(3):
        cli.link_needs(inst, store=store)

    out = capsys.readouterr().out
    assert out.count("feature/1: now waits for dep group 1 to merge") == 1


# --- 1.4 an in-review unit sent back while gated parks ------------------------------


def test_an_in_review_unit_sent_back_while_its_gate_is_unmet_is_gated_until_it_clears(
    inst: Installation,
    store: UnitStore,
    builder: Builder,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store.upsert([stored("feature/1"), stored("dep/1", repo="platform"), stored("slow/1")])
    store.set_state("dep/1", HELD)
    monkeypatch.setattr(cli, "REFRESH_SECONDS", 0.05)
    sent: list[int] = []

    def poll(inst, **kwargs) -> None:
        # The gate is written and a review comment sends the unit back.
        if store.get("feature/1").state == IN_REVIEW and not sent:
            sent.append(1)
            write_needs(inst)  # every round recomputes the gate from tasks.md
            store.set_dependencies("feature/1", ("dep/1",))
            store.set_merge_before("feature/1", ("dep/1",))
            store.set_state("feature/1", PLANNED, note="reworking", cause=Cause.REWORK)

    monkeypatch.setattr(cli, "poll_all", poll)
    builder.scripts["slow/1"] = lambda: time.sleep(0.4)

    assert tick(inst) == 0

    assert builder.started.count("feature/1") == 1, "not started again while the gate is unmet"
    after = store.get("feature/1")
    assert (after.state, after.cause) == (PLANNED, Cause.GATED)

    store.set_state("dep/1", MERGED, pr=3)
    assert tick(inst) == 0

    assert builder.started.count("feature/1") == 2
    assert store.get("feature/1").state == IN_REVIEW


# --- 1.5 a Needs-only edit is applied without a re-plan ------------------------------


@pytest.mark.parametrize("before", ["", "Needs: dep group 1 — it reshapes the runtime\n\n"])
def test_a_needs_only_edit_is_not_planned_again_and_the_gate_applies_next_tick(
    inst: Installation, store: UnitStore, monkeypatch: pytest.MonkeyPatch, before: str
) -> None:
    """Writing a gate on a group, or adding `merged` to a dependency it already
    has, is the whole edit: nothing for the planner to see."""
    folder = inst.root / "openspec" / "changes" / "feature"
    folder.mkdir(parents=True)
    tasks = folder / "tasks.md"

    def text(needs: str) -> str:
        return (
            "# Tasks\n\nAcceptance: none — a scheduling rule.\n\n"
            f"## 1. [app] [tier1] The work\n\n{needs}- [ ] 1.1 Test: it\n- [ ] 1.2 Do it\n"
        )

    tasks.write_text(text(before))
    calls: list[str] = []

    def plan_round(**kwargs):
        calls.append("plan")
        return SimpleNamespace(units=(stored("feature/1"),), joins=())

    monkeypatch.setattr(cli, "plan_round", plan_round)
    plan_all(inst, store=store)
    assert calls == ["plan"]
    store.upsert([stored("dep/1")])
    store.set_state("feature/1", RUNNING, branch="spec/feature/1")

    tasks.write_text(text(f"{NEEDS}\n"))
    plan_all(inst, store=store)
    cli.link_needs(inst, store=store)

    assert calls == ["plan"], "the edit reached the planner"
    assert store.get("feature/1").merge_before == ("dep/1",)


def test_status_lists_a_gated_unit_as_waiting_on_the_group(
    inst: Installation,
    store: UnitStore,
    thread: Thread,
    capsys: pytest.CaptureFixture[str],
) -> None:
    gated_failure(store)
    assert main(["requeue", "feature/1"]) == 0
    capsys.readouterr()

    assert cli.cmd_status(argparse.Namespace(), inst) == 0

    lines = capsys.readouterr().out.splitlines()
    waiting = next(line for line in lines if "feature/1" in line and "waiting" in line)
    assert "dep group 1" in waiting
    assert not any("feature/1" in line and "failed" in line for line in lines[1:])


# --- a stacking parent is not a merge gate -------------------------------------------


def test_a_unit_sent_back_while_its_stacking_parent_reworks_is_not_gated(
    store: UnitStore,
) -> None:
    """`feature/1` stacked on `dep/1`, same repo, no `Needs:` line: it only
    needs the parent back in review, so no merge is involved."""
    store.upsert([stored("dep/1"), stored("feature/1", depends_on=("dep/1",))])
    store.set_state("dep/1", PLANNED, note="reworking", cause=Cause.REWORK)
    store.set_state("feature/1", PLANNED, note="reworking", cause=Cause.REWORK)

    cli.gate_sent_back(store)

    assert store.get("feature/1").cause is Cause.REWORK


def test_a_failed_child_requeued_while_its_parent_reworks_resumes_instead_of_waiting_to_merge(
    store: UnitStore, thread: Thread, capsys: pytest.CaptureFixture[str]
) -> None:
    store.upsert([stored("dep/1"), stored("feature/1", depends_on=("dep/1",))])
    store.set_state("dep/1", PLANNED, note="reworking", cause=Cause.REWORK)
    store.set_state("feature/1", FAILED, branch="spec/feature/1")

    assert main(["requeue", "feature/1"]) == 0

    (call,) = thread.delivered
    assert call["requeue"] is RequeueReason.RESUME
    assert store.get("feature/1").cause is not Cause.GATED
    assert "to merge" not in capsys.readouterr().out
