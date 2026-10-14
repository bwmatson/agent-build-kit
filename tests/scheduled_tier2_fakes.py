"""A scheduled unit, the default branch it runs on and the archive step, for the tests of what a
scheduled tier 2 unit does."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_build_kit.config import Tier2UnitScope
from agent_build_kit.graph.state import ResumeEvent
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.tier2_schedule import scheduled_name, write_due
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Unit, branch_name
from agent_build_kit.pipeline.wiring import reset_to
from agent_build_kit.pipeline.workspaces import prepare_worktree, worktree_path
from tests.factories import git, init_repo, stored_unit, unit
from tests.graph_driver import tick
from tests.runner_fakes import Recorder
from tests.tier2_schedule_fakes import TODAY, planning, store_of
from tests.tier2_scope_fakes import Ran, session

CHANGE = scheduled_name("app", TODAY)
TEST_BODY = "def test_live():\n    assert True\n"
SUMMARY = "=" * 20 + " 2 passed, 1 skipped in 0.10s " + "=" * 20 + "\n"


def scheduled_unit() -> Unit:
    return unit(f"{CHANGE}/1", change=CHANGE, tier="tier2", title="Run the full tier 2 suite")


def default_branch(repo: Path) -> tuple[Path, str]:
    """A repo on its default branch with a tier 2 test; the tree is its base. Returns the
    repo and the base's sha."""
    init_repo(repo)
    (repo / "pyproject.toml").write_text("[project]\nname = 'app'\n")
    (repo / "tests" / "live").mkdir(parents=True)
    (repo / "tests" / "live" / "test_live.py").write_text(TEST_BODY)
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")
    return repo, git(repo, "rev-parse", "HEAD").strip()


def written_change(tmp_path: Path, **limits: Any) -> tuple[Installation, UnitStore, StoredUnit]:
    """A planning directory in which the round's write step has written the scheduled change
    of `app`, and a store holding its unit as the planner makes it."""
    inst = planning(tmp_path / "plan", **limits)
    store = store_of(inst, "app")
    assert write_due(inst, store, today=TODAY, say=lambda line: None) == [CHANGE]
    stored = stored_unit(f"{CHANGE}/1", change=CHANGE, tier="tier2", groups=(1,))
    store.upsert([stored])
    return inst, store, stored


def archiving(args: list[str], *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess:
    """The OpenSpec CLI's archive: the change's directory moves under `archive/`, dated."""
    change = args[args.index("archive") + 1]
    changes = cwd / "openspec" / "changes"
    (changes / "archive").mkdir(exist_ok=True)
    (changes / change).rename(changes / "archive" / f"{TODAY.isoformat()}-{change}")
    return subprocess.CompletedProcess(args, 0, "archived\n", "")


class ScheduledRun:
    """The scheduled unit of a written change on the graph, over the default branch, with the
    tier 2 runner `make_ran(tree)` answers and a real tier 2 session in between. `tree` is where
    the unit's worktree is made, by the real `prepare_worktree`, which keeps the branch between
    runs as the pipeline's does. `tick` runs or resumes its thread, as a tick does."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        make_ran: Callable[[Path], Any] = lambda tree: Ran(SUMMARY),
        scope: Tier2UnitScope = Tier2UnitScope.OWN,
        feedback: str = "",
        limits: dict[str, Any] | None = None,
        **overrides: Any,
    ) -> None:
        self.tmp_path = tmp_path
        self.inst, self.store, stored = written_change(tmp_path, **(limits or {}))
        self.root = tmp_path / "trees"
        self.repo, self.base = default_branch(self.inst.checkouts["app"])
        self.tree = worktree_path(self.repo, branch_name(scheduled_unit()), self.root)
        self.ran = make_ran(self.tree)
        self.log: list[str] = []
        self.gate = session(tmp_path, self.ran, scope=scope, log=self.log, subject=scheduled_unit())
        self.recorder = Recorder(self.store)
        if feedback:
            self.store.set_feedback(stored.id, feedback)
        self.overrides: dict[str, Any] = dict(
            planning_repo=self.inst.root,
            worktree=self.worktree,
            reset_to=reset_to,
            run_tier2=self.gate.run,
            tier2_passed_note=self.gate.passed_note,
            tier2_verdict=lambda: self.gate.verdict,
            **overrides,
        )

    def worktree(self, unit: Unit, base: str, allow_dirty: bool = False) -> Path:
        return prepare_worktree(self.repo, branch_name(unit), base=base, root=self.root)

    def advance(self, name: str, text: str = "fixed\n") -> str:
        """A commit on the default branch, as a merged fix is; returns the new tip."""
        (self.repo / name).write_text(text)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-qm", f"add {name}")
        return git(self.repo, "rev-parse", "HEAD").strip()

    def tick(self, event: ResumeEvent | None = None, **more: Any) -> RunOutcome:
        return tick(
            self.tmp_path,
            self.recorder,
            event=event,
            tier="tier2",
            subject=scheduled_unit(),
            **{**self.overrides, **more},
        )

    @property
    def stored(self) -> StoredUnit:
        return self.store.get(scheduled_unit().id)
