"""A `Needs:` line on a parent in another repository added after a unit has started gates it.

A failed or held unit requeued before its prerequisite merges waits as `planned`
with the cause `gated` and is resumed, in the mode it was requeued with, once
the prerequisite lands. A running unit is told, not disturbed, and a parent in
another repository never becomes the unit's base.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from agent_build_kit.cli import main
from agent_build_kit.cli import pipeline as cli
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
)
from agent_build_kit.pipeline.usage_guard import Decision
from tests.conftest import make_installation
from tests.factories import stored_unit

pytestmark = pytest.mark.usefixtures("scripted_engine")

NEEDS = "Needs: dep group 1 — it reshapes the runtime\n"


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
        project_limits={"max_concurrent_stacks": 2, "max_units_in_progress": 50},
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
        f"# Tasks\n\n## {group}. [app] [unit-test] The work\n\n{NEEDS}\n- [ ] {group}.1 Test: it\n"
    )
    return tasks


def gated_failure(store: UnitStore, *, state=FAILED) -> None:
    """`feature/1` stopped with a thread, then a `Needs:` on `dep/1` (in another
    repository, still in review) was written for it."""
    store.upsert(
        [
            stored("dep/1", repo="platform"),
            stored("feature/1", depends_on=("dep/1",)),
        ]
    )
    store.set_state("dep/1", IN_REVIEW, pr=3)
    store.set_state("feature/1", state, branch="spec/feature/1")
    store.set_feedback("feature/1", "e2e-test failed: the dev stack is down")


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
    assert after.feedback == "e2e-test failed: the dev stack is down"
    out = capsys.readouterr().out
    assert "dep group 1" in out, "the command names the group it waits for"


def test_requeue_of_a_gated_unit_keeps_the_saved_feedback_when_reworking(
    store: UnitStore, thread: Thread
) -> None:
    gated_failure(store)

    assert main(["requeue", "feature/1", "--rework"]) == 0

    after = store.get("feature/1")
    assert (after.state, after.cause) == (PLANNED, Cause.GATED)
    assert after.feedback == "e2e-test failed: the dev stack is down"
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


# --- 1.4 an in-review unit sent back while gated parks ------------------------------


# --- 1.5 a Needs-only edit is applied without a re-plan ------------------------------


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


def test_a_unit_sent_back_while_a_parent_in_another_repo_is_unmerged_waits_for_the_merge(
    inst: Installation,
    store: UnitStore,
    builder: Builder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    write_needs(inst)
    store.upsert(
        [
            stored("dep/1", repo="platform"),
            stored("feature/1", depends_on=("dep/1",)),
        ]
    )
    store.set_state("dep/1", IN_REVIEW, pr=3)
    store.set_state("feature/1", PLANNED, note="reworking", cause=Cause.REWORK)

    cli.gate_sent_back(store)

    gated = store.get("feature/1")
    assert (gated.state, gated.cause) == (PLANNED, Cause.GATED)
    assert "dep group 1" in gated.note
    assert "to merge" in gated.note

    store.set_state("dep/1", MERGED, pr=3)
    assert tick(inst) == 0
    assert "feature/1" in builder.started


def test_a_failed_child_requeued_while_its_parent_reworks_waits_until_the_parent_is_back_in_review(
    inst: Installation,
    store: UnitStore,
    thread: Thread,
    builder: Builder,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store.upsert([stored("dep/1"), stored("feature/1", depends_on=("dep/1",))])
    store.set_state("dep/1", PLANNED, note="reworking", cause=Cause.REWORK)
    store.set_state("feature/1", FAILED, branch="spec/feature/1")

    assert main(["requeue", "feature/1"]) == 0

    after = store.get("feature/1")
    assert (after.state, after.cause) == (PLANNED, Cause.GATED)
    assert thread.delivered == []
    out = capsys.readouterr().out
    assert "dep group 1" in out
    assert "to merge" not in out

    store.set_state("dep/1", IN_REVIEW, pr=3)
    assert tick(inst) == 0

    (call,) = thread.delivered
    assert call["unit"] == "feature/1"
    assert call["requeue"] is RequeueReason.RESUME
