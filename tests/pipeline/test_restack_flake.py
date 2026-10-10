"""A child restacked after its parent merged, whose tier 1 meets a flake, is recorded and
parked to wait on the fix instead of being left unmoved (spec: flaky-tests)."""

from __future__ import annotations

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.flakes import FlakeFound, flake_change_name, flake_record
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.unit_store import Cause, RequeueReason, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.wiring import build_on_flake
from agent_build_kit.pipeline.work_graph import group_needs
from tests.factories import stored_unit
from tests.graph.test_flake_parking import FLAKE, TEST
from tests.pipeline.test_flake_fix_change import change_with_unit, code_repo


def restack_of(store: UnitStore, installation: Installation, pushed: list[str], child: StoredUnit):
    def flaking(**kwargs: object):
        raise FlakeFound((FLAKE,))

    restack = events.build_restack(
        repos={"app": installation.checkouts["app"]},
        store=store,
        root=installation.root,
        move=lambda *a, **k: Moved(sha="newsha"),
        tier1=flaking,
        on_flake=build_on_flake(store, installation, log=lambda message: None),
        push=lambda *a, **k: pushed.append("pushed") or "newsha",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: "same-diff",
        head_of=lambda repo, branch: "approved",
    )

    def run() -> None:
        restack(
            branch="spec/feature/1",
            old_base="spec/parent/1",
            new_base="main",
            child=child,
            parent=stored_unit("parent/1", change="parent", pr=1, branch="spec/parent/1"),
        )

    return run


def test_a_flake_met_while_restacking_is_recorded_and_the_child_waits_for_its_fix(
    installation: Installation,
) -> None:
    code_repo(installation)
    child = change_with_unit(installation, "feature", "feature/1").model_copy(
        update={"pr": 2, "branch": "spec/feature/1", "approved": "approved"}
    )
    store = UnitStore(installation.root / "units.json")
    store.upsert([child])
    pushed: list[str] = []

    restack_of(store, installation, pushed, child)()

    (recorded,) = flake_record(installation).entries()
    assert (recorded.test, recorded.unit) == (TEST, "feature/1")
    fix = flake_change_name(TEST)
    assert recorded.change == fix
    assert [n.change for n in group_needs(installation.changes_dir / "feature/tasks.md")[1]] == [
        fix
    ]
    stored = store.get("feature/1")
    assert (stored.state, stored.cause) == (PLANNED, Cause.GATED)
    assert stored.gated_requeue is RequeueReason.RESUME
    assert TEST in stored.note
    assert pushed == [], "the branch is not pushed over the reviewable head"


def test_a_flake_met_by_a_unit_of_its_own_fix_change_fails_the_restack_as_before(
    installation: Installation,
) -> None:
    code_repo(installation)
    fix = flake_change_name(TEST)
    owner = change_with_unit(installation, "feature", "feature/1")
    store = UnitStore(installation.root / "units.json")
    store.upsert([owner])
    build_on_flake(store, installation, log=lambda message: None)(owner, FLAKE)
    own = stored_unit(f"{fix}/1", change=fix, groups=(1,), pr=3, approved="approved")
    store.upsert([own])

    with pytest.raises(RuntimeError, match="checks fail"):
        restack_of(store, installation, [], own)()
