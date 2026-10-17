"""The merge handler hands its old base to unit-test on a clean move, and only on a clean
move (spec: a-moved-base-is-checked-by-what-it-can-affect).

A changed diff or a resolution is planned for review without unit-test running, as before.
"""

from __future__ import annotations

from itertools import count
from typing import Any

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.restack import Moved
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import stored_unit
from tests.pipeline.test_flake_fix_change import change_with_unit, code_repo

OLD_BASE = "spec/parent/1"


class UnitTest:
    """Unit-test as the handler calls it: what each call was given, and a pass."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def __call__(self, **kwargs: Any) -> tuple[bool, str]:
        self.calls.append(kwargs)
        return True, ""


def restacking(
    installation: Installation, moved: Moved, *, name: str = "feature", diff_changes: bool = False
):
    """The handler over unit `name`, approved at `approved`, and a way to run it; returns the
    store, the unit-test it was given, the pushes and the run."""
    child = change_with_unit(installation, name, f"{name}/1").model_copy(
        update={"pr": 2, "branch": f"spec/{name}/1", "approved": "approved"}
    )
    store = UnitStore(installation.root / f"{name}.json")
    store.upsert([child])
    unit_test, pushed = UnitTest(), []
    diffs = count()
    restack = events.build_restack(
        repos={"app": installation.checkouts["app"]},
        store=store,
        root=installation.root,
        move=lambda *a, **k: moved,
        unit_test=unit_test,
        push=lambda *a, **k: pushed.append("pushed") or "newsha",
        retarget=lambda *a, **k: None,
        comment=lambda *a, **k: None,
        diff_id=lambda repo, base, branch: f"diff-{next(diffs) if diff_changes else 0}",
        head_of=lambda repo, branch: "approved",
    )

    def run() -> None:
        restack(
            branch=f"spec/{name}/1",
            old_base=OLD_BASE,
            new_base="main",
            child=child,
            parent=stored_unit("parent/1", change="parent", pr=1, branch=OLD_BASE),
        )

    return store, unit_test, pushed, run


def test_a_clean_move_passes_its_old_base_to_unit_test_and_is_pushed(
    installation: Installation,
) -> None:
    code_repo(installation)
    store, unit_test, pushed, run = restacking(installation, Moved(sha="newsha"))

    run()

    assert [call.get("moved_from") for call in unit_test.calls] == [OLD_BASE]
    assert pushed == ["pushed"]


def test_a_changed_diff_or_a_resolution_is_planned_for_review_without_unit_test(
    installation: Installation,
) -> None:
    code_repo(installation)
    clean = restacking(installation, Moved(sha="newsha"), name="clean")
    changed = restacking(installation, Moved(sha="newsha"), name="changed", diff_changes=True)
    resolved = restacking(installation, Moved(sha="newsha", resolved=("a.py",)), name="resolved")
    for _, _, _, run in (clean, changed, resolved):
        run()

    assert [call.get("moved_from") for call in clean[1].calls] == [OLD_BASE]
    for name, (store, unit_test, pushed, _) in (("changed/1", changed), ("resolved/1", resolved)):
        stored = store.get(name)
        assert (stored.state, stored.cause) == (PLANNED, Cause.RESTACK_DEFERRED)
        assert unit_test.calls == []
        assert pushed == []


Tier1 = UnitTest  # abk-shim
