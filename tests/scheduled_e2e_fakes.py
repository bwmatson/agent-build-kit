"""A scheduled unit, the default branch it runs on and the archive step, for the tests of what a
scheduled e2e-test unit does."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from agent_build_kit.config import REST_SPLIT, E2eSplit, E2eUnitScope
from agent_build_kit.graph.state import ResumeEvent
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.e2e_schedule import scheduled_name, write_due
from agent_build_kit.pipeline.stack_runner import RunOutcome
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import Unit, branch_name
from agent_build_kit.pipeline.wiring import reset_to
from agent_build_kit.pipeline.workspaces import prepare_worktree, worktree_path
from tests.e2e_park_fakes import holds_of
from tests.e2e_schedule_fakes import TODAY, planning, store_of
from tests.e2e_scope_fakes import KIT_SPLITS, Ran, branch, session
from tests.factories import git, stored_unit, unit
from tests.graph_driver import tick
from tests.runner_fakes import Recorder

CHANGE = scheduled_name("app", TODAY)
TEST_BODY = "def test_live():\n    assert True\n"
SUMMARY = "=" * 20 + " 2 passed, 1 skipped in 0.10s " + "=" * 20 + "\n"


# The two splits a repo declares in the tests that run a split of its own.
DECLARED = {
    "e2e_splits": {
        "acp": {"marker": "runtime_acp"},
        "claude_code": {"marker": "runtime_claude_code"},
    }
}


def scheduled_unit(split: str = REST_SPLIT) -> Unit:
    change = scheduled_name("app", TODAY, split)
    return unit(f"{change}/1", change=change, tier="e2e-test", title="Run the full e2e-test suite")


def default_branch(repo: Path, *, dev_stack: str | None = None) -> tuple[Path, str]:
    """A repo on its default branch with an e2e test, and the dev stack script `dev_stack`
    if given; the tree is its base. Returns the repo and the base's sha."""
    files = {"tests/live/test_live.py": TEST_BODY}
    if dev_stack:
        files[dev_stack] = "#!/bin/sh\n"
    return branch(repo.parent, None, base_files=files, repo=repo)


def written_change(
    tmp_path: Path,
    split: str = REST_SPLIT,
    *,
    tests: dict[str, Any] | None = None,
    **limits: Any,
) -> tuple[Installation, UnitStore, StoredUnit]:
    """A planning directory in which the round's write step has written the scheduled changes
    of `app` (`tests` declares its splits), and a store holding the unit of `split`'s as the
    planner makes it."""
    inst = planning(tmp_path / "plan", tests=tests, **limits)
    store = store_of(inst, "app")
    written = write_due(inst, store, today=TODAY, say=lambda line: None)
    change = scheduled_unit(split).change
    assert change in written
    stored = stored_unit(f"{change}/1", change=change, tier="e2e-test", groups=(1,))
    store.upsert([stored])
    return inst, store, stored


def archiving_on(day: date) -> Callable[..., subprocess.CompletedProcess]:
    """The OpenSpec CLI's archive run on `day`: the change's directory moves under `archive/`,
    prefixed with that day."""

    def archive(args: list[str], *, cwd: Path, **kwargs: object) -> subprocess.CompletedProcess:
        change = args[args.index("archive") + 1]
        changes = cwd / "openspec" / "changes"
        (changes / "archive").mkdir(exist_ok=True)
        (changes / change).rename(changes / "archive" / f"{day.isoformat()}-{change}")
        return subprocess.CompletedProcess(args, 0, "archived\n", "")

    return archive


archiving = archiving_on(TODAY)


class ScheduledRun:
    """The scheduled unit of a written change on the graph, over the default branch, with the
    e2e-test runner `make_ran(tree)` answers and a real e2e-test session in between. The unit is
    that
    of the change of `split`, whose repo declares its splits when `declared` or `split` is not
    `rest`; `held` maps the splits held now to their reasons, and may be emptied to release
    them. `tree` is where
    the unit's worktree is made, by the real `prepare_worktree`, which keeps the branch between
    runs as the pipeline's does. `tick` runs or resumes its thread, as a tick does."""

    def __init__(
        self,
        tmp_path: Path,
        *,
        make_ran: Callable[[Path], Any] = lambda tree: Ran(SUMMARY),
        scope: E2eUnitScope = E2eUnitScope.OWN,
        feedback: str = "",
        limits: dict[str, Any] | None = None,
        dev_stack: str | None = None,
        split: str = REST_SPLIT,
        declared: bool = False,
        held: dict[str, str] | None = None,
        **overrides: Any,
    ) -> None:
        self.tmp_path = tmp_path
        self.subject = scheduled_unit(split)
        self.declared = declared or split != REST_SPLIT
        self.held: dict[str, str] = {} if held is None else held
        self.inst, self.store, stored = written_change(
            tmp_path,
            split,
            tests=DECLARED if self.declared else None,
            **(limits or {}),
        )
        self.root = tmp_path / "trees"
        self.repo, self.base = default_branch(self.inst.checkouts["app"], dev_stack=dev_stack)
        self.tree = worktree_path(self.repo, branch_name(self.subject), self.root)
        self.ran = make_ran(self.tree)
        self.log: list[str] = []
        self.gate = session(
            tmp_path,
            self.ran,
            scope=scope,
            log=self.log,
            subject=self.subject,
            dev_stack=dev_stack,
            held=self.held.keys(),
            splits=KIT_SPLITS if self.declared else (E2eSplit(name=REST_SPLIT),),
        )
        self.recorder = Recorder(self.store)
        if feedback:
            self.store.set_feedback(stored.id, feedback)
        self.overrides: dict[str, Any] = dict(
            planning_repo=self.inst.root,
            worktree=self.worktree,
            reset_to=reset_to,
            run_e2e=self.gate.run,
            e2e_passed_note=self.gate.passed_note,
            e2e_verdict=lambda: self.gate.verdict,
            e2e_result=lambda: self.gate.result,
            e2e_holds=lambda: holds_of(**self.held),
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
            tier="e2e-test",
            subject=self.subject,
            **{**self.overrides, **more},
        )

    @property
    def stored(self) -> StoredUnit:
        return self.store.get(self.subject.id)
