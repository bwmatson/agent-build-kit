"""A group carried only by a retired unit is not built: a `Needs:` line on it is neither linked
to the retired unit nor counted as planned (spec: a-started-unit-keeps-its-groups)."""

from __future__ import annotations

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import UnitState
from tests.factories import stored_unit

DEPENDENT = "# Tasks\n\n## 1. [app] [unit-test] G\n\nNeeds: base group 3 — why\n\n- [ ] 1.1 Do it\n"
BASE = "# Tasks\n\n## 3. [app] [unit-test] H\n\n- [ ] 3.1 Do it\n"


def released_group(inst: Installation, store: UnitStore) -> StoredUnit:
    """`feature/1` needs base group 3, whose only carrier `base/2` is retired."""
    for change, text in (("feature", DEPENDENT), ("base", BASE)):
        path = inst.changes_dir / change / "tasks.md"
        path.parent.mkdir(parents=True)
        path.write_text(text)
    store.upsert(
        [
            stored_unit("feature/1", change="feature", groups=(1,)),
            stored_unit("base/2", change="base", groups=(3,)),
        ]
    )
    store.set_state("base/2", UnitState.RETIRED, branch="spec/base/2")
    return store.get("feature/1")


def test_a_needs_line_on_a_group_only_a_retired_unit_carried_waits_for_a_plan(
    installation: Installation,
) -> None:
    store = UnitStore(installation.root / "units.json")
    dependent = released_group(installation, store)

    assert cli.awaiting_planning(installation, dependent, store.all()) == ["base group 3"]


def test_link_needs_does_not_depend_on_a_retired_unit(installation: Installation) -> None:
    store = UnitStore(installation.root / "units.json")
    released_group(installation, store)

    cli.link_needs(installation, store=store)

    assert store.get("feature/1").depends_on == ()
