"""What the tick-scheduling tests share: a builder whose completions a test controls, a
workspace of fixture units, and the stubs that isolate a pass from everything around it.

The builder marks the store the way the real one does: `running` while it builds,
`in_review` once its PR is open, and back to `planned` when it pauses or is held."""

from __future__ import annotations

import argparse
import sqlite3
import threading
from collections.abc import Callable
from contextlib import closing
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.checkpointer import unit_graphs_path
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, PLANNED, RUNNING, UnitState
from agent_build_kit.pipeline.usage_guard import Decision
from tests.conftest import make_installation

MOVED_NOTE = "held before implement: its base moved from spec/a/1 to main while it built"


def warm_unit_graphs(tmp_path: Path) -> None:
    """The unit-graph database already in WAL, so builds opening it together do
    not race to switch the journal mode (`database is locked`)."""
    with closing(sqlite3.connect(unit_graphs_path(tmp_path))) as conn:
        conn.execute("PRAGMA journal_mode=WAL")


def isolate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything around building stubbed: GitHub, the network, planning,
    live verification and the usage window. Tests about those replace the
    stub they need."""
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(
        cli, "may_start_unit", lambda r, **_: Decision(may_start=True, reason="plenty")
    )


def workspace(tmp_path: Path, *, max_concurrent: int = 4, depth_cap: int = 3) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        limits={"stack_depth_build_cap": depth_cap},
        project_limits={"max_concurrent_stacks": max_concurrent, "max_units_in_progress": 50},
    )


def stored(uid: str, **overrides) -> StoredUnit:
    change, _, _ = uid.partition("/")
    defaults: dict = {
        "id": uid,
        "change": change,
        "title": f"Build {uid}",
        "repo": "app",
        "tier": "tier1",
        "depends_on": (),
        "estimated_lines": 140,
        "groups": (1,),
    }
    return StoredUnit(**{**defaults, **overrides})


def tick(inst: Installation, *, only: list[str] | None = None) -> int:
    args = argparse.Namespace(dry_run=False)
    if only is not None:
        args.only = only
    return cli.cmd_tick(args, inst)


class Builder:
    """Stands in for `build_runner`: each unit's build runs its script, if it
    has one, and ends as the script says — "open" by default."""

    def __init__(self, store: UnitStore) -> None:
        self.store = store
        self.scripts: dict[str, Callable[[], str | None]] = {}
        # Run before the build marks its unit `running`, as the real one's
        # lock, store read and usage check are.
        self.before_running: dict[str, Callable[[], object]] = {}
        # How a unit's build ends when it is not in review: the state, cause and
        # note it leaves. A unit not named here is left `planned` with its status as note.
        self.ends: dict[str, tuple[UnitState, Cause | None, str]] = {}
        self.started: list[str] = []
        self.finished: list[str] = []
        self._lock = threading.Lock()
        self._prs = 0

    def __call__(self, unit, **kwargs) -> Builder._Run:
        return Builder._Run(self)

    class _Run:
        def __init__(self, builder: Builder) -> None:
            self.builder = builder

        def run(self, unit, *, base, graph) -> RunOutcome:
            return self.builder._run(unit)

    def _run(self, unit) -> RunOutcome:
        with self._lock:
            self.started.append(unit.id)
        self.before_running.get(unit.id, lambda: None)()
        self.store.set_state(unit.id, RUNNING, branch=f"spec/{unit.id}")
        try:
            status = self.scripts.get(unit.id, lambda: None)() or "open"
        finally:
            with self._lock:
                self._prs += 1
                pr = self._prs

        if status == "open":
            self.store.set_state(unit.id, IN_REVIEW, pr=pr)
        elif unit.id in self.ends:
            state, cause, note = self.ends[unit.id]
            held_by = HOLDERS.get(cause, HeldBy.NONE) if state == HELD and cause else HeldBy.NONE
            self.store.set_state(unit.id, state, note=note, cause=cause, held_by=held_by)
        else:
            note = status if ":" in status else f"{status} before implement"
            self.store.set_state(unit.id, PLANNED, note=note)
        with self._lock:
            self.finished.append(unit.id)
        return RunOutcome(
            status=RunStatus(status.split()[0].rstrip(":")), detail=f"{status} {unit.id}", pr=pr
        )


# Who really holds a unit for each cause that ends a run `held`.
HOLDERS = {
    Cause.TOOLCHAIN: HeldBy.TOOLCHAIN,
    Cause.DEPTH: HeldBy.DEPTH,
    Cause.REVIEW_ESCALATED_CLASS: HeldBy.REVIEW,
    Cause.REVIEW_ESCALATED_DISAGREEMENT: HeldBy.REVIEW,
    Cause.NEEDS_HUMAN: HeldBy.REVIEW,
}


def install_builder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Builder:
    """A `Builder` over a fresh store, standing in for the tick's `build_runner`."""
    fake = Builder(UnitStore(tmp_path / "units.json"))
    monkeypatch.setattr(cli, "build_runner", fake)
    return fake
