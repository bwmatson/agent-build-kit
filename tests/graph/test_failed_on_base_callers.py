"""Every caller of unit-test handles a failure that is not the unit's: a group already built
whose whole-repo run raises it parks the unit, and so does a restack (spec: regression-agent).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.flakes import FailedOnBase, Flake, flake_record
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.wiring import build_on_flake
from agent_build_kit.pipeline.work_graph import group_needs
from tests.factories import stored_unit
from tests.graph.branch_fakes import UNIT, prepared
from tests.graph.test_build_path import build
from tests.pipeline.test_flake_fix_change import TEST, change_with_unit, code_repo

FAILING = Flake(
    test=TEST,
    command="uv run pytest -n auto -q",
    output="FAILED tests/test_widget.py::test_renders_the_label - assert 'a' == 'b'\n",
    at=datetime(2026, 3, 1, 9, 30, tzinfo=UTC),
)


def raising(**kwargs: object):
    raise FailedOnBase((FAILING,))


class Told:
    """What the runner was told of each failing test, and for which unit."""

    def __init__(self) -> None:
        self.told: list[tuple[str, str, bool]] = []

    def __call__(self, unit, flake: Flake, *, wait: bool = True) -> str:
        self.told.append((unit.id, flake.test, flake.failing))
        return "fix-test-widget"


def test_a_group_already_built_whose_run_raises_it_parks_the_unit_gated(tmp_path: Path) -> None:
    recorder, _ = prepared(tmp_path, silent_groups=(1, 2, 3))
    told = Told()

    overrides: dict[str, Any] = recorder.overrides(tmp_path)
    overrides.update(run_unit_test=raising, on_flake=told)

    outcome = build(tmp_path, recorder, **overrides)

    assert outcome.status == RunStatus.HELD
    stored = recorder.store.get(UNIT)
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert stored.gated_requeue is RequeueReason.RESUME
    assert "failing test" in stored.note and TEST in stored.note
    assert told.told == [(UNIT, TEST, True)]


def restack_of(store: UnitStore, installation: Installation, child: StoredUnit):
    pushed: list[str] = []
    restack = events.build_restack(
        repos={"app": installation.checkouts["app"]},
        store=store,
        root=installation.root,
        move=lambda *a, **k: Moved(sha="newsha"),
        unit_test=raising,
        on_flake=build_on_flake(store, installation, log=lambda message: None),
        push=lambda *a, **k: pushed.append("pushed") or "newsha",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: "approved",
    )
    restack(
        branch="spec/feature/1",
        old_base="spec/parent/1",
        new_base="main",
        child=child,
        parent=stored_unit("parent/1", change="parent", pr=1, branch="spec/parent/1"),
    )
    return pushed


def test_a_restack_whose_run_raises_it_waits_gated_for_the_fix_and_records_no_flake(
    installation: Installation,
) -> None:
    code_repo(installation)
    child = change_with_unit(installation, "feature", "feature/1").model_copy(
        update={"pr": 2, "branch": "spec/feature/1", "approved": "approved"}
    )
    store = UnitStore(installation.root / "units.json")
    store.upsert([child])

    pushed = restack_of(store, installation, child)

    stored = store.get("feature/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert stored.gated_requeue is RequeueReason.RESUME
    assert "failing test" in stored.note and "flaky" not in stored.note
    assert len(group_needs(installation.changes_dir / "feature" / "tasks.md")[1]) == 1
    assert flake_record(installation).entries() == [], "it did not flake"
    assert pushed == []
