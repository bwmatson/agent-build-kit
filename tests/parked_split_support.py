"""Units parked for a held e2e-test split, and the delivery that resumes them (spec:
e2e-runtime-parking): one installation that declares the splits, a unit parked on them and a
stand-in for the thread a resume is delivered to."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_holds import SOURCE_COMMAND, SOURCE_GATE, write_hold
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.usage_guard import Decision
from agent_build_kit.pipeline.workspaces import BranchBusy
from tests.conftest import make_installation
from tests.factories import stored_unit

__all__ = ["Deliveries", "hold", "installation", "park", "store_of", "stub_round"]


def installation(
    tmp_path: Path,
    *,
    acp: bool | None = True,
    claude_code: bool | None = None,
    gate: dict[str, Any] | None = None,
    claude_code_gate: dict[str, Any] | None = None,
    **overrides: Any,
) -> Installation:
    """Two splits declared for every repo; `acp` and `claude_code` carry the configured `hold`
    given (None leaves the entry without one) and each the gate given for it. The state directory
    is the planning root."""
    splits: dict[str, dict[str, Any]] = {}
    for name, configured in (("acp", acp), ("claude_code", claude_code)):
        splits[name] = {"marker": f"runtime_{name}"}
        if configured is not None:
            splits[name]["hold"] = configured
    if gate is not None:
        splits["acp"]["gate"] = gate
    if claude_code_gate is not None:
        splits["claude_code"]["gate"] = claude_code_gate
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        tests={"e2e_splits": splits},
        **overrides,
    )


def stub_round(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything a round reaches that is not under test: GitHub, planning, the usage window."""
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "plan_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "has_identity", lambda inst, repo: True)
    monkeypatch.setattr(cli, "archive_ready_changes", lambda *a, **k: [])
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    monkeypatch.setattr(cli, "may_start_unit", lambda r: Decision(may_start=True, reason="ok"))


def store_of(inst: Installation) -> UnitStore:
    return UnitStore(inst.state_dir / "units.json")


def park(
    store: UnitStore,
    uid: str = "feature/1",
    splits: tuple[str, ...] = ("acp",),
    *,
    repo: str = "app",
) -> None:
    """`uid` as a run leaves it when its e2e tests of `splits` did not run: planned, with the
    cause `split_held`, a branch, and the splits and commit the run was on."""
    store.upsert([stored_unit(uid, change=uid.partition("/")[0], repo=repo)])
    store.set_state(
        uid,
        PLANNED,
        branch=f"spec/{uid}",
        note=f"e2e tests of {', '.join(splits)} did not run: the split is held",
        cause=Cause.SPLIT_HELD,
    )
    store.set_parked(uid, splits, "abc1234", "e2e-test passed the other groups")


def hold(inst: Installation, split: str = "acp", *, until: datetime | None = None) -> None:
    """A hold in the state file: a gate's when it has a deadline, else a person's command."""
    write_hold(
        inst.state_dir,
        split,
        reason="the usage window is spent",
        source=SOURCE_GATE if until else SOURCE_COMMAND,
        by="test",
        until=until,
        now=datetime.now(UTC),
    )


class Deliveries:
    """The thread a release is delivered to: what `resume_thread` is handed, and the units whose
    branch another run holds."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, *, busy: tuple[str, ...] = ()) -> None:
        self.delivered: list[tuple[str, str]] = []
        self.busy = busy
        monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: True)
        monkeypatch.setattr(cli, "resume_thread", self.resume)

    def resume(self, inst: Installation, unit: Any, kind: str, **kwargs: Any) -> None:
        if unit.id in self.busy:
            raise BranchBusy("another run holds the branch")
        self.delivered.append((unit.id, kind))
