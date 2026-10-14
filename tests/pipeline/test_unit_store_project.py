"""A stored unit's project: read as the root when absent, kept through a re-plan."""

from __future__ import annotations

import json
from pathlib import Path

from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import FAILED
from tests.factories import unit


def test_a_record_stored_before_projects_reads_as_the_root_and_the_next_write_records_it(
    tmp_path: Path,
) -> None:
    path = tmp_path / "units.json"
    store = UnitStore(path)
    store.upsert([unit("feature/1", change="feature")])
    store.set_state("feature/1", FAILED, branch="spec/feature/1")
    stored = json.loads(path.read_text())
    for record in stored["units"]:
        record.pop("project", None)
    path.write_text(json.dumps(stored))

    assert UnitStore(path).get("feature/1").project == "."

    # A re-plan that tags the group for a project does not move the started unit.
    UnitStore(path).upsert([unit("feature/1", change="feature", project="web")])

    assert [record["project"] for record in json.loads(path.read_text())["units"]] == ["."]


def test_a_replan_leaves_a_started_units_project_and_gives_a_new_unit_its_groups(
    tmp_path: Path,
) -> None:
    path = tmp_path / "units.json"
    store = UnitStore(path)
    store.upsert([unit("feature/1", change="feature", project="web")])
    store.set_state("feature/1", FAILED, branch="spec/feature/1")

    store.upsert(
        [
            unit("feature/1", change="feature", project="."),
            unit("feature/2", change="feature", groups=(2,), project="services/api"),
        ]
    )

    assert {u.id: u.project for u in UnitStore(path).all()} == {
        "feature/1": "web",
        "feature/2": "services/api",
    }
    assert UnitStore(path).get("feature/1").state == FAILED
