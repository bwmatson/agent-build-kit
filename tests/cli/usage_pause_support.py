"""What the tests of a usage pause at the gate share: a workspace with two accounts, a round run
over it, and a unit left paused for usage (running, a thread, no lock, a pause that ends at a
time). The usage decision is `Accounts` of the admission tests, answering per account; the clock
is the fake one, so a pause ends when a test moves it."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.checkpointer import unit_graphs_path
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import wiring
from agent_build_kit.pipeline.unit_store import Cause, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.cli.test_admission_asks_own_account import PERSONAL, Accounts
from tests.conftest import make_installation
from tests.tick_pass import stored


def isolate_round(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Accounts:
    """Everything around a round stubbed but the usage decision, which is returned: it allows
    every account until a test fills one (`full`)."""
    for name in ("poll_all", "fetch_all", "plan_all"):
        monkeypatch.setattr(cli, name, lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "verify_ready", lambda inst, units, **kwargs: lambda change: True)
    (tmp_path / "planning").mkdir()
    with closing(sqlite3.connect(unit_graphs_path(tmp_path / "planning"))) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
    accounts = Accounts()
    # One source for admission and for the gate of an agent step (`build_usage_gate`).
    monkeypatch.setattr(cli, "decide_start", accounts)
    monkeypatch.setattr(wiring, "decide_start", accounts)
    return accounts


def workspace(
    tmp_path: Path, units: list[StoredUnit], *, limit: int = 50, workers: int = 2
) -> tuple[Installation, UnitStore]:
    """`app` on the default account and `platform` on `personal`, with `limit` units in progress
    and `workers` build workers for each."""
    inst = make_installation(
        tmp_path / "planning",
        planning={"state_dir": ".", "worktree_root": str(tmp_path / "trees")},
        project_limits={"max_units_in_progress": limit, "max_concurrent_stacks": workers},
        repos={
            "app": {"path": str(tmp_path / "app"), "slug": "example/app"},
            "platform": {
                "path": str(tmp_path / "platform"),
                "slug": "example/platform",
                "account": PERSONAL,
            },
        },
        runtimes={"claude_code": {"accounts": {PERSONAL: {"config_dir": str(tmp_path / "p")}}}},
    )
    inst.state_dir.mkdir(parents=True, exist_ok=True)
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert(units)
    return inst, store


def unit(uid: str, repo: str = "app", **overrides) -> StoredUnit:
    return stored(uid, repo=repo, **overrides)


def with_threads(monkeypatch: pytest.MonkeyPatch, *unit_ids: str) -> None:
    """Only these units have a thread a run left."""
    monkeypatch.setattr(cli, "has_thread", lambda _inst, unit_id: unit_id in unit_ids)


def pause_for_usage(store: UnitStore, unit_id: str, until: datetime) -> None:
    """The unit as the gate leaves it: `running` on its branch, no lock, paused until `until`."""
    store.set_state(unit_id, RUNNING, branch=f"spec/{unit_id}", cause=Cause.USAGE)
    store.set_usage_pause(unit_id, until)


def started_by(inst: Installation, store: UnitStore, **kwargs) -> list[str]:
    """The ids the next round would start or resume, in order."""
    ready = cli.run_round(
        inst,
        store,
        building=kwargs.pop("building", ()),
        only=frozenset(),
        submit=True,
        **kwargs,
    )
    return [each.id for each in ready]
