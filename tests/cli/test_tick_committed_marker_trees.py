"""The committed-marker delivery test builds its unit's branch in a worktree. The worktree root
was `tmp_path.parent / "trees"`, which every test of a pytest worker shares, so a worktree an
earlier test left for the same repository and branch made the test fail or not by which tests
the worker had run before it. An installation of its own keeps the worktree in the test's
own directory."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from agent_build_kit.pipeline.units import RUNNING
from tests.attach_driver import checked_out
from tests.conftest import make_private_trees_installation

UNIT = "feature/1"


def test_the_units_worktree_is_built_in_the_tests_own_directory_not_the_workers_shared_one(
    tmp_path: Path,
) -> None:
    inst = make_private_trees_installation(tmp_path, project_limits={"max_units_in_progress": 50})
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert(
        [
            StoredUnit(
                id=UNIT,
                change="feature",
                title="Build",
                repo="app",
                tier="unit-test",
                depends_on=(),
                estimated_lines=140,
                groups=(1,),
            )
        ]
    )
    store.set_state(UNIT, RUNNING, branch="spec/feature/1")
    tree = checked_out(inst, UNIT)

    assert tmp_path in tree.parents, f"{tree} is outside the test's own directory"
