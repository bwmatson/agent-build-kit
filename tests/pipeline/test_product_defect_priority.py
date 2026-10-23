"""Two units that meet one defect share the change written at the first one's priority, and
the planner's priority-edge promotion raises it to the more urgent dependent as for any
prerequisite (spec: e2e-group-scope)."""

from __future__ import annotations

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.planner import promote_ancestors
from agent_build_kit.pipeline.work_graph import validate_tasks
from tests.factories import groups_at, stored_unit
from tests.product_defect_fakes import FIX, defect, met_by, reporter

FIX_UNIT = f"{FIX}/1"


def test_the_change_is_written_at_the_priority_of_the_unit_that_met_the_defect_first(
    installation: Installation,
) -> None:
    first = met_by(installation, "first", "first/1", priority=2)
    second = met_by(installation, "second", "second/1", priority=1)
    hook, _ = reporter(installation, first, second)

    written = hook(first, defect())
    shared = hook(second, defect())

    assert written == shared == FIX
    groups, _ = validate_tasks(installation.changes_dir / FIX / "tasks.md", repos=("app",))
    assert [group.priority for group in groups] == [2]


def test_promotion_raises_the_shared_change_to_the_more_urgent_dependent(
    installation: Installation,
) -> None:
    first = met_by(installation, "first", "first/1", priority=2)
    second = met_by(installation, "second", "second/1", priority=1)
    hook, store = reporter(installation, first, second)
    hook(first, defect())
    hook(second, defect())
    groups, _ = validate_tasks(installation.changes_dir / FIX / "tasks.md", repos=("app",))
    store.upsert(
        [
            stored_unit(FIX_UNIT, change=FIX, groups=(1,), priority=2),
            first.model_copy(update={"depends_on": (FIX_UNIT,)}),
            second.model_copy(update={"depends_on": (FIX_UNIT,)}),
        ]
    )
    catalog = {FIX: groups, "first": groups_at(2), "second": groups_at(1)}

    promoted = promote_ancestors(store, catalog)

    assert promoted == [(FIX_UNIT, 1, "second/1")]
    fix = store.get(FIX_UNIT)
    assert (fix.priority, fix.promoted_from) == (1, "second/1")
