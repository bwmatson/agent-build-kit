"""What the plan-review tests share: a planning repo with one change and planned units, a stand-in
model client that answers in the raw shape a model sends, and a tick over them.

The model is faked at the runtime seam (`StandInRuntime`), as the planner's is; the build is the
shared `Builder`, so what a tick started is `builder.started`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit import runtimes
from agent_build_kit.config import dump
from agent_build_kit.installation import Installation
from tests.conftest import make_installation
from tests.runtimes.stand_in import StandInRuntime
from tests.tick_pass import Builder, install_builder, isolate, stored, tick

CHANGE = "feature"
PROPOSAL = "PROPOSAL-TEXT: why the feature is wanted"
DESIGN = "DESIGN-TEXT: how the feature is built"
SPEC = "SPEC-TEXT: the feature SHALL work"
TASKS = """# Tasks

Acceptance: none — a fixture about plan review

## 1. [app] [unit-test] First group

- [ ] 1.1 Test: `tests/test_shared.py` asserts it.
- [ ] 1.2 Do it.

## 2. [app] [unit-test] Second group

- [ ] 2.1 Test: `tests/test_shared.py` asserts it again.
- [ ] 2.2 Do it.
"""
EDITED_TASKS = TASKS + "\n## 3. [app] [unit-test] Third group\n\n- [ ] 3.1 Test: it.\n"
FINDING = {
    "group": 2,
    "question": 1,
    "evidence": "group 2 renames what tests/test_shared.py asserts",
}


def reply(*findings: dict) -> str:
    """What a model answers: prose, then the findings as JSON."""
    return "I read the plan.\n\n" + json.dumps({"findings": list(findings)})


class Review:
    """A planning repo holding `feature` with two planned units, ticked with a fake model."""

    def __init__(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, review_plans: bool = True
    ) -> None:
        isolate(monkeypatch)
        self.inst: Installation = make_installation(
            tmp_path,
            planning={
                "state_dir": ".",
                "worktree_root": str(tmp_path.parent / "trees"),
                "review_plans": review_plans,
            },
            project_limits={"max_concurrent_stacks": 4, "max_units_in_progress": 50},
        )
        self.config = self.inst.root / "abk.yaml"
        self.config.write_text(dump(self.inst.config))
        monkeypatch.chdir(self.inst.root)
        folder = self.inst.changes_dir / CHANGE
        (folder / "specs" / "feature").mkdir(parents=True)
        (folder / "proposal.md").write_text(PROPOSAL)
        (folder / "design.md").write_text(DESIGN)
        (folder / "specs" / "feature" / "spec.md").write_text(SPEC)
        self.edit_tasks(TASKS)
        self.runtime = StandInRuntime(answer=reply())
        monkeypatch.setattr(runtimes, "active", lambda: self.runtime)
        self.builder: Builder = install_builder(tmp_path, monkeypatch)
        self.builder.store.upsert([stored(f"{CHANGE}/1"), stored(f"{CHANGE}/2")])

    def edit_tasks(self, text: str) -> None:
        (self.inst.changes_dir / CHANGE / "tasks.md").write_text(text)

    def tick(self) -> int:
        return tick(self.inst)

    @property
    def asked(self) -> int:
        return len(self.runtime.requests)

    @property
    def prompt(self) -> str:
        return self.runtime.requests[0].prompt
