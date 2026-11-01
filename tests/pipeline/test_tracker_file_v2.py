"""The version 2 mapping file: items by level, the version 1 reader, the target hash and the
unit's `story` field read and not written (spec: tracker-levels)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent_build_kit.pipeline.tracker_file import (
    Synced,
    TargetMismatch,
    TaskEntry,
    TrackerFile,
    mapping_target,
    parent_item,
    read_for_target,
    read_tracker,
    write_tracker,
)
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import HELD
from agent_build_kit.trackers.config import TrackerSection, section_for
from tests.factories import stored_unit
from tests.trackers.tracker_section_support import AZURE_BLOCK, configure

TYPES = {"epic": "Epic", "change": "Feature", "group": "Issue", "task": "Task"}


def change_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "openspec" / "changes" / "feature"
    folder.mkdir(parents=True)
    (folder / "tasks.md").write_text("# Tasks\n")
    return folder


def section(
    levels: list[str], *, epic: bool = True, types: dict[str, str] | None = None
) -> TrackerSection:
    configure(
        app={
            "kind": "azure_devops",
            "levels": levels,
            "epic": epic,
            "azure_devops": {**AZURE_BLOCK, "types": types or TYPES},
        }
    )
    found = section_for("app")
    assert found is not None
    return found


def by_level(target: str) -> TrackerFile:
    return TrackerFile(
        schema_version=2,
        kind="azure_devops",
        target=target,
        change=Synced(id="100", fields={"title": "Feature"}, revision="7"),
        epic="259",
        groups={
            "feature:1": Synced(id="101", fields={"state": "Doing"}, revision="2"),
            "feature:2": Synced(id="102", revision="5"),
        },
        tasks={
            "feature:1.1": TaskEntry(
                id="103", fields={"state": "Done"}, revision="3", text_hash="abc123"
            ),
        },
    )


def test_a_version_2_file_records_every_level_and_round_trips_equal(tmp_path: Path) -> None:
    folder = change_dir(tmp_path)
    written = by_level(mapping_target(section(["change", "group", "task"])))

    write_tracker(folder, written)

    assert read_tracker(folder) == written
    raw = yaml.safe_load((folder / "tracker.yaml").read_text())
    assert raw["schema_version"] == 2
    assert raw["change"]["id"] == "100"
    assert raw["epic"] == "259"
    assert raw["groups"]["feature:2"]["revision"] == "5"
    assert raw["tasks"]["feature:1.1"]["fields"] == {"state": "Done"}


def test_a_version_1_file_is_read_with_its_feature_as_the_change_item(tmp_path: Path) -> None:
    folder = change_dir(tmp_path)
    (folder / "tracker.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "azure_devops",
                "target": "example",
                "feature": {"id": "100", "fields": {"title": "Feature"}, "revision": "7"},
                "tasks": {"feature:1.1": {"id": "101", "revision": "3", "text_hash": "abc123"}},
            }
        )
    )

    found = read_tracker(folder)

    assert found is not None
    assert found.change == Synced(id="100", fields={"title": "Feature"}, revision="7")
    assert found.tasks == {"feature:1.1": TaskEntry(id="101", revision="3", text_hash="abc123")}
    assert found.groups == {}
    assert found.epic is None


def test_a_file_written_under_one_mapping_is_not_reused_under_another(tmp_path: Path) -> None:
    folder = change_dir(tmp_path)
    two = mapping_target(section(["change", "group"]))
    three = mapping_target(section(["change", "group", "task"]))
    write_tracker(folder, by_level(two))

    assert read_for_target(folder, "azure_devops", two) is not None
    with pytest.raises(TargetMismatch):
        read_for_target(folder, "azure_devops", three)


def test_the_same_mapping_gives_the_same_target_and_another_gives_another() -> None:
    two = section(["change", "group"])

    assert mapping_target(two) == mapping_target(section(["change", "group"]))
    assert mapping_target(two) != mapping_target(section(["change"]))
    assert mapping_target(two).startswith(two.target)


def test_a_changed_type_for_a_level_in_use_gives_another_target() -> None:
    levels = ["change", "group"]
    other = {**TYPES, "group": "User Story"}

    assert mapping_target(section(levels)) != mapping_target(section(levels, types=other))


def test_turning_the_epic_on_or_changing_its_type_gives_another_target() -> None:
    levels = ["change", "group"]
    renamed = {**TYPES, "epic": "Initiative"}

    off = mapping_target(section(levels, epic=False))

    assert off != mapping_target(section(levels, epic=True))
    assert mapping_target(section(levels)) != mapping_target(section(levels, types=renamed))


def test_an_unused_epic_type_does_not_change_the_target() -> None:
    levels = ["change", "group"]
    without = {name: kind for name, kind in TYPES.items() if name != "epic"}

    found = mapping_target(section(levels, epic=False, types=TYPES))

    assert found == mapping_target(section(levels, epic=False, types=without))
    assert found == mapping_target(
        section(levels, epic=False, types={**TYPES, "epic": "Initiative"})
    )


def test_a_units_story_is_read_and_not_written_back(tmp_path: Path) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.import_units([stored_unit("app/1", change="app")])
    document = json.loads(store.path.read_text())
    document["units"][0]["story"] = "story-7"
    store.path.write_text(json.dumps(document))

    assert UnitStore(store.path).get("app/1").story == "story-7"

    UnitStore(store.path).set_state("app/1", HELD)

    raw = json.loads(store.path.read_text())["units"][0]
    assert "story" not in raw


def test_a_version_1_file_without_a_feature_is_written_back_as_version_2(tmp_path: Path) -> None:
    folder = change_dir(tmp_path)
    (folder / "tracker.yaml").write_text(
        yaml.safe_dump({"schema_version": 1, "kind": "azure_devops", "target": "example"})
    )

    found = read_tracker(folder)
    assert found is not None
    write_tracker(folder, found)

    raw = yaml.safe_load((folder / "tracker.yaml").read_text())
    assert raw["schema_version"] == 2
    assert "feature" not in raw


def test_a_version_1_file_with_a_feature_is_written_back_without_it(tmp_path: Path) -> None:
    folder = change_dir(tmp_path)
    (folder / "tracker.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "kind": "azure_devops",
                "target": "example",
                "feature": {"id": "100"},
            }
        )
    )

    found = read_tracker(folder)
    assert found is not None
    write_tracker(folder, found)

    raw = yaml.safe_load((folder / "tracker.yaml").read_text())
    assert raw["schema_version"] == 2
    assert raw["change"]["id"] == "100"
    assert "feature" not in raw


def test_a_tasks_parent_is_its_group_item_under_three_levels() -> None:
    found = parent_item(by_level("t"), section(["change", "group", "task"]), "task", "feature:1.1")

    assert found == "101"


def test_a_tasks_parent_is_the_change_item_under_two_levels() -> None:
    found = parent_item(by_level("t"), section(["change", "task"]), "task", "feature:1.1")

    assert found == "100"


def test_a_groups_parent_is_the_change_item() -> None:
    found = parent_item(by_level("t"), section(["change", "group", "task"]), "group", "feature:2")

    assert found == "100"


def test_the_first_level_hangs_under_the_epic_when_one_is_set_and_nowhere_otherwise() -> None:
    levels = ["change", "group"]

    assert parent_item(by_level("t"), section(levels, epic=True), "change", "feature") == "259"
    assert parent_item(by_level("t"), section(levels, epic=False), "change", "feature") is None


def test_a_parent_that_is_not_recorded_gives_none() -> None:
    bare = TrackerFile(kind="azure_devops", target="t")
    levels = ["change", "group", "task"]

    assert parent_item(bare, section(levels), "task", "feature:1.1") is None
    assert parent_item(bare, section(levels), "group", "feature:1") is None
