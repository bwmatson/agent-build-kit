"""The rework of an `[e2e-test]` unit reads the builder's account: a valid `product-defect`
block files the fix change and parks the unit on it, no block is an ordinary rework, and a
refused block stops the unit and files nothing (spec: e2e-group-scope)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, RequeueReason
from agent_build_kit.pipeline.units import PLANNED, Unit
from agent_build_kit.pipeline.wiring import build_on_product_defect
from agent_build_kit.pipeline.work_graph import group_needs
from tests.conftest import make_installation
from tests.factories import git
from tests.graph.test_e2e_rework_prompt import FAILED_E2E
from tests.graph.test_e2e_scope_guard import (
    PRODUCT,
    PRODUCT_BASE,
    PRODUCT_CHANGED,
    TEST,
    UNIT,
    Scoped,
)
from tests.product_defect_fakes import FIX, account, defect


class Reworked:
    """An e2e unit stopped for a product file, given an e2e failure to rework, over a planning
    repo that is the installation the product-defect hook files its change in."""

    def __init__(self, tmp_path: Path) -> None:
        self.scoped = Scoped(tmp_path, PRODUCT_CHANGED, base_files=PRODUCT_BASE)
        self.inst = make_installation(tmp_path / "meta")
        self.log: list[str] = []
        self.told: list[tuple[str, str]] = []
        self.scoped.build()
        recorder = self.scoped.recorder
        recorder.store.set_feedback(UNIT, FAILED_E2E, source=FeedbackSource.E2E)
        recorder.events.clear()
        recorder.subjects.clear()
        self.real = build_on_product_defect(recorder.store, self.inst, log=self.log.append)

    def hook(self, unit: Unit, report: Any) -> str | None:
        self.told.append((unit.id, report.test))
        return self.real(unit, report)

    def rework(self, answering: Callable[[str], str]):
        recorder = self.scoped.recorder

        def run(prompt: str, **kwargs: Any) -> str:
            recorder.claude(prompt, **kwargs)
            return answering(prompt)

        return self.scoped.build(run=run, on_product_defect=self.hook)

    @property
    def tasks(self) -> Path:
        return self.inst.changes_dir / "add-marker" / "tasks.md"

    @property
    def changes(self) -> set[str]:
        return {path.name for path in self.inst.changes_dir.iterdir() if path.is_dir()}


def test_a_valid_report_files_the_change_and_parks_the_unit_on_it(tmp_path: Path) -> None:
    reworked = Reworked(tmp_path)

    outcome = reworked.rework(lambda prompt: account(defect(files=[PRODUCT])))

    assert outcome.status == RunStatus.HELD, outcome
    assert reworked.told == [(UNIT, TEST)]
    assert FIX in reworked.changes
    assert [need.change for need in group_needs(reworked.tasks)[1]] == [FIX]
    stored = reworked.scoped.stored
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert stored.gated_requeue is RequeueReason.RESUME
    assert stored.feedback == "", "so the wait's end resumes the unit and does not rework it"
    assert FIX in stored.note or TEST in stored.note, "a person sees what it waits on"
    recorder = reworked.scoped.recorder
    assert not any(subject.startswith("fix:") for subject in recorder.subjects)
    assert not {"unit-test", "review", "push", "pr"} & set(recorder.events)


def test_an_account_with_no_block_is_an_ordinary_rework_that_commits_a_fix(
    tmp_path: Path,
) -> None:
    reworked = Reworked(tmp_path)
    scoped = reworked.scoped

    def restoring(prompt: str) -> str:
        git(scoped.repo, "restore", "--source", scoped.base, "--", PRODUCT)
        scoped.commit_all("restore the product file")
        return "fixed the test"

    reworked.rework(restoring)

    assert reworked.told == []
    assert reworked.changes == {"add-marker"}
    assert any(subject.startswith("fix:") for subject in scoped.recorder.subjects)
    assert "unit-test" in scoped.recorder.events, "it goes on to the checks"
    assert scoped.stored.cause is not Cause.GATED


def test_a_refused_block_stops_the_unit_with_the_reason_and_files_nothing(
    tmp_path: Path,
) -> None:
    reworked = Reworked(tmp_path)
    tests_only = defect(files=[TEST.partition("::")[0]])

    outcome = reworked.rework(lambda prompt: account(tests_only))

    assert outcome.status == "failed", outcome
    assert "fault in the test" in outcome.detail
    assert reworked.told == [], "nothing was filed or recorded"
    assert reworked.changes == {"add-marker"}
    assert group_needs(reworked.tasks).get(1, []) == []
    assert reworked.scoped.stored.cause is not Cause.GATED
