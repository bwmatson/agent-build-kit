"""A unit about to run e2e-test while a fix change of a base failure is open: the planning
repo, the record, the fix change, and the node driven with the gate and a fake scope."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.graph.state import EventKind, ResumeEvent
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.file_lock import file_lock
from agent_build_kit.pipeline.flakes import fix_change_name
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import RequeueReason, UnitStore
from agent_build_kit.pipeline.untouched_failures import PREFIX
from agent_build_kit.pipeline.wiring import build_on_e2e_gate, build_on_preexisting
from agent_build_kit.pipeline.work_graph import group_needs
from tests.conftest import make_installation
from tests.e2e_wait_fakes import OLD, OTHER_OLD, Failing, snapshot_of, verdict_of
from tests.factories import stored_unit
from tests.graph_driver import fresh, tick
from tests.runner_fakes import Recorder

GATE_CLEARED = ResumeEvent(
    kind=EventKind.REQUEUE, requeue=RequeueReason.RESUME, reason="gate cleared"
)
TWO_GROUPS = (
    "# Tasks\n\n## 1. [app] [e2e-test] First\n\n- [ ] 1.1 Test: it\n- [ ] 1.2 Make it\n\n"
    "## 2. [app] [e2e-test] Second\n\n- [ ] 2.1 Test: it\n- [ ] 2.2 Make it\n"
)


def write_change(installation: Installation, change: str) -> None:
    tasks = installation.changes_dir / change / "tasks.md"
    tasks.parent.mkdir(parents=True)
    tasks.write_text(TWO_GROUPS)


def open_fix(
    store: UnitStore,
    installation: Installation,
    test: str = OLD,
    *,
    met_by: str = "feature/1",
    repo: str = "app",
    with_unit: bool = True,
    split: str = "",
) -> str:
    """Record `test` as failing on the base, met by `met_by` of `repo`, and write its
    fix change through the code that records a failure (a unit that does not wait).
    The fix change gets its unit in the store when `with_unit`. `split` is the e2e-test
    split the failing test belongs to."""
    change = met_by.split("/")[0]
    if not (installation.changes_dir / change).exists():
        write_change(installation, change)
    met = stored_unit(met_by, change=change, repo=repo, groups=(1, 2))
    store.upsert([met])
    verdict = verdict_of(old=(test,), group=split)
    build_on_preexisting(store, installation, log=lambda m: None)(
        met, verdict, verdict.pre_existing[0], wait=False
    )
    fix = fix_change_name(test, PREFIX)
    assert (installation.changes_dir / fix).is_dir()
    if with_unit:
        store.upsert([stored_unit(f"{fix}/1", change=fix, repo=repo, groups=(1,))])
    return fix


class Scope:
    """The scope function the node asks: `whole` says the run executes the whole marker."""

    def __init__(self, *, whole: bool) -> None:
        self.whole = whole
        self.asked: list[tuple[Path, str | None]] = []

    def __call__(self, *, cwd: Path, base: str | None) -> bool:
        self.asked.append((cwd, base))
        return self.whole


class Gate:
    """The real gate callable, counting how often the node asked it."""

    def __init__(self, inner: Callable[..., list[str]]) -> None:
        self.inner = inner
        self.asked: list[str] = []

    def __call__(self, unit: Any, **run: Any) -> list[str]:
        self.asked.append(unit.id)
        return self.inner(unit, **run)


class Planning:
    """A planning repo with a unit `add-marker/1` of two groups, the node's driver and
    the record of base failures, as one installation has them."""

    def __init__(
        self, tmp_path: Path, *, repo: str = "app", whole: bool = True, **config: Any
    ) -> None:
        self.tmp_path = tmp_path
        self.installation: Installation = make_installation(
            tmp_path,
            planning=dict(state_dir=".", worktree_root=str(tmp_path.parent / "trees")),
            **config,
        )
        self.recorder: Recorder = fresh(tmp_path)
        self.store = self.recorder.store
        self.write_change("add-marker")
        self.store.upsert([stored_unit("add-marker/1", repo=repo, groups=(1, 2))])
        self.scope = Scope(whole=whole)
        self.gate = Gate(build_on_e2e_gate(self.store, self.installation, log=lambda m: None))

    def write_change(self, change: str) -> None:
        write_change(self.installation, change)

    def open_fix(self, test: str = OLD, **kwargs: Any) -> str:
        """See `open_fix`, here over this planning repo."""
        return open_fix(self.store, self.installation, test, **kwargs)

    def needs(self, change: str = "add-marker") -> dict[int, list[str]]:
        """The changes each group of `change` has a `Needs:` line on."""
        tasks = self.installation.changes_dir / change / "tasks.md"
        return {group: [n.change for n in found] for group, found in group_needs(tasks).items()}

    def changes(self) -> set[str]:
        return {
            p.name
            for p in self.installation.changes_dir.iterdir()
            if p.is_dir() and p.name != "archive"
        }

    def tick(self, **more: Any) -> RunOutcome:
        """The unit reaches e2e-test (or is resumed there), `run_e2e` being the recorder's
        unless `more` says otherwise."""

        def run_under_lock(*, cwd: Path, base: str | None = None) -> tuple[bool, str]:
            """The recorder's e2e-test, taking the stack lock as `E2eSession.run` does."""
            with file_lock(self.installation.e2e_lock):
                return self.recorder.e2e(cwd=cwd, base=base)

        wired: dict[str, Any] = dict(
            tier="e2e-test",
            e2e_runs_whole=self.scope,
            on_e2e_gate=self.gate,
            run_e2e=run_under_lock,
        )
        return tick(self.tmp_path, self.recorder, **{**wired, **more})

    def fails(self, *, split: str) -> RunStatus:
        """The unit's e2e-test run fails on `OLD` of split `split`, which the base fails too."""
        e2e = Failing(self.recorder.events, snapshot_of(OLD), verdict_of(old=(OLD,), group=split))
        return self.tick(
            run_e2e=e2e.run,
            e2e_verdict=e2e.judged,
            on_preexisting=build_on_preexisting(self.store, self.installation, log=lambda m: None),
        ).status

    def fix_changes(self) -> list[str]:
        """The open changes that fix a failing test."""
        return sorted(c for c in self.changes() if c.startswith(PREFIX))

    def status(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> list[str]:
        """`abk status` over the store, after the `Needs:` lines are linked."""
        cli.link_needs(self.installation, store=self.store)
        monkeypatch.setattr(cli, "current_usage", lambda: None)
        assert cli.cmd_status(argparse.Namespace(), self.installation) == 0
        return capsys.readouterr().out.splitlines()

    @property
    def ran_e2e(self) -> bool:
        return "e2e-test" in self.recorder.events


__all__ = ["GATE_CLEARED", "OLD", "OTHER_OLD", "Gate", "Planning", "Scope"]
