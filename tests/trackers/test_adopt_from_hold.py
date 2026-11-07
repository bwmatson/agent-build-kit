"""The item ids a hold records seed the tracker mapping: hand-made items are adopted, checked and
completed by the reconciler, never duplicated (spec: external-hold-adoption)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit import trackers
from agent_build_kit.forges.transport import RateLimited
from agent_build_kit.pipeline.external_file import Hold, write_holds
from agent_build_kit.pipeline.tracker_file import (
    Synced,
    TrackerFile,
    mapping_target,
    read_tracker,
    write_tracker,
)
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.trackers.base import Item
from agent_build_kit.trackers.local import EPIC_TYPE
from agent_build_kit.trackers.reconciler import PassReport, read_snapshot, reconcile
from tests.trackers.board_support import (
    CHANGE,
    board_section,
    browse_example,
    covering,
    write_change,
)
from tests.trackers.reconciler_support import RecordingTracker, World

OTHER = "other-change"
PERSON_TITLE = "Sam's own wording for the lane work"


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def world_for(tmp_path: Path, levels: list[str], *, epic: bool = False) -> World:
    # The stand-in reports a manual parent under its own type name.
    section = board_section(levels, epic=epic, epic_type=EPIC_TYPE if epic else None)
    return World(tmp_path, section, RecordingTracker())


def hand_made(
    world: World,
    kind: str,
    title: str,
    parent: str | None = None,
    *,
    body: str = "",
    markers: tuple[str, ...] = (),
) -> Item:
    """An item a person made on the board; the calls made to make it are not the sync's."""
    made = world.tracker.create(kind, title, body, parent, markers=markers)
    world.tracker.calls.clear()
    return made


def hold_with(
    world: World, items: Mapping[str, str | list[str]], scope: tuple[int, ...] = (1,)
) -> None:
    write_holds(
        world.change_dir,
        [
            Hold(
                scope=scope,
                holder="Sam Example",
                link="https://boards.example/items/42",
                since=datetime(2026, 1, 1, tzinfo=UTC),
                items=dict(items),
            )
        ],
    )


def run(world: World, *groups: int) -> PassReport:
    return world.run([covering(f"{CHANGE}/1", groups or (1,))])


def creates(world: World) -> list[tuple[str, str]]:
    return [(call.args[0], call.kwargs["markers"][0]) for call in world.tracker.made("create")]


def recorded(world: World) -> TrackerFile:
    found = read_tracker(world.change_dir)
    assert found is not None
    return found


def named(report: PassReport, *texts: str) -> bool:
    """Whether one conflict names every text."""
    return any(all(text in conflict for text in texts) for conflict in report.conflicts)


def test_a_hand_made_change_and_group_item_are_adopted_and_the_tasks_made_under_the_group(
    tmp_path: Path,
) -> None:
    world = world_for(tmp_path, ["change", "group", "task"])
    change = hand_made(world, "change", "Remember lanes")
    group = hand_made(world, "group", PERSON_TITLE, change.id)
    hold_with(world, {"change": change.id, "group": group.id})

    report = run(world)

    mapping = recorded(world)
    assert mapping.change is not None and mapping.change.id == change.id
    assert mapping.groups[f"{CHANGE}:1"].id == group.id
    made = creates(world)
    assert ("change", CHANGE) not in made
    assert ("group", f"{CHANGE}:1") not in made
    assert [
        marker for kind, marker in made if kind == "task" and marker.startswith(f"{CHANGE}:1.")
    ] == [
        f"{CHANGE}:1.1",
        f"{CHANGE}:1.2",
    ]
    parents = {call.kwargs["markers"][0]: call.args[3] for call in world.tracker.made("create")}
    assert parents[f"{CHANGE}:1.1"] == group.id
    assert report.conflicts == ()


def test_the_old_keys_feature_and_story_are_adopted_as_change_and_group(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group", "task"])
    change = hand_made(world, "change", "Remember lanes")
    group = hand_made(world, "group", PERSON_TITLE, change.id)
    hold_with(world, {"feature": change.id, "story": group.id})

    run(world)

    mapping = recorded(world)
    assert mapping.change is not None and mapping.change.id == change.id
    assert mapping.groups[f"{CHANGE}:1"].id == group.id
    assert ("change", CHANGE) not in creates(world)
    assert ("group", f"{CHANGE}:1") not in creates(world)


def test_a_two_level_board_adopts_per_level_and_makes_no_task_items(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    change = hand_made(world, "change", "Remember lanes")
    group = hand_made(world, "group", PERSON_TITLE, change.id)
    hold_with(world, {"change": change.id, "group": group.id})

    run(world)

    mapping = recorded(world)
    assert mapping.change is not None and mapping.change.id == change.id
    assert mapping.groups[f"{CHANGE}:1"].id == group.id
    assert all(kind != "task" for kind, _ in creates(world))
    assert world.tracker.get(group.id).parent_id == change.id


def test_recorded_task_ids_are_adopted_under_their_group_item(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group", "task"])
    change = hand_made(world, "change", "Remember lanes")
    group = hand_made(world, "group", PERSON_TITLE, change.id)
    first = hand_made(world, "task", "Gap fill", group.id)
    second = hand_made(world, "task", "Conflicts", group.id)
    hold_with(world, {"change": change.id, "group": group.id, "tasks": [first.id, second.id]})

    report = run(world)

    mapping = recorded(world)
    assert mapping.tasks[f"{CHANGE}:1.1"].id == first.id
    assert mapping.tasks[f"{CHANGE}:1.2"].id == second.id
    assert not [marker for kind, marker in creates(world) if kind == "task" and ":1." in marker]
    assert report.conflicts == ()


def test_an_epic_id_is_the_manual_parent_and_is_never_written(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"], epic=True)
    epic = world.tracker.add_epic("Lane quarter")
    hold_with(world, {"epic": epic.id})

    report = run(world)

    assert recorded(world).epic == epic.id
    touching = [call for call in world.tracker.calls if call.args and call.args[0] == epic.id]
    assert touching
    assert not [call for call in world.tracker.writes() if call.args and call.args[0] == epic.id]
    assert report.conflicts == ()


def test_an_adopted_item_keeps_the_persons_wording(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    change = hand_made(world, "change", "Remember lanes")
    group = hand_made(world, "group", PERSON_TITLE, change.id, body="what Sam wrote")
    hold_with(world, {"change": change.id, "group": group.id})

    run(world)

    assert world.tracker.get(group.id).title == PERSON_TITLE
    assert recorded(world).groups[f"{CHANGE}:1"].fields["title"] == PERSON_TITLE


def test_the_marker_is_attached_without_a_conflict_and_finds_the_item(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    change = hand_made(world, "change", "Remember lanes")
    group = hand_made(world, "group", PERSON_TITLE, change.id, body="what Sam wrote")
    hold_with(world, {"change": change.id, "group": group.id})

    first = run(world)
    second = run(world)

    found = world.tracker.find_by_marker(f"{CHANGE}:1")
    assert found is not None and found.id == group.id
    assert found.body == "what Sam wrote"
    assert len(world.tracker.made("add_marker")) == 2, "one for the change, one for the group"
    assert first.conflicts == () and second.conflicts == ()


def test_the_markers_the_kit_wrote_when_adopting_are_recorded_as_its_own(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    change = hand_made(world, "change", "Remember lanes")
    group = hand_made(world, "group", PERSON_TITLE, change.id)
    hold_with(world, {"change": change.id, "group": group.id})

    run(world)

    written = read_snapshot(world.snapshot)["written"]
    assert isinstance(written, dict)
    assert world.tracker.get(group.id).revision in written[group.id]
    assert world.tracker.get(change.id).revision in written[change.id]


def test_an_adopted_item_keeps_its_wording_when_its_unit_moves_and_the_heading_changes(
    tmp_path: Path,
) -> None:
    world = world_for(tmp_path, ["change", "group"])
    change = hand_made(world, "change", "Remember lanes")
    group = hand_made(world, "group", PERSON_TITLE, change.id, body="what Sam wrote")
    hold_with(world, {"change": change.id, "group": group.id})
    key = f"{CHANGE}:1"
    run(world)

    world.run([covering(f"{CHANGE}/1", (1,), UnitState.IN_REVIEW)])
    tasks = world.change_dir / "tasks.md"
    tasks.write_text(
        tasks.read_text().replace("Gap fill, conflicts and remembered lanes", "Renamed")
    )
    world.run([covering(f"{CHANGE}/1", (1,), UnitState.IN_REVIEW)])

    on_group = [call for call in world.tracker.made("update") if call.args[0] == group.id]
    assert on_group, "the move to review was written"
    assert all(not {"title", "body"} & set(call.args[1]) for call in on_group)
    assert world.tracker.get(group.id).title == PERSON_TITLE
    entry = recorded(world).groups[key]
    assert entry.adopted
    assert entry.fields["title"] == PERSON_TITLE
    assert entry.fields["body"] == "what Sam wrote"


def test_when_adopting_fails_nothing_is_created_for_the_held_change(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    change = hand_made(world, "change", "Remember lanes")
    hold_with(world, {"change": change.id})
    world.tracker.fail = lambda call: (
        RuntimeError("the board is down") if call.name == "get" else None
    )

    report = run(world)

    assert creates(world) == []
    assert report.errors == 1


def test_a_rate_limit_while_adopting_ends_the_pass(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    change = hand_made(world, "change", "Remember lanes")
    hold_with(world, {"change": change.id})
    world.tracker.fail = lambda call: (
        RateLimited("slow down", retry_after=None) if call.name == "get" else None
    )

    report = run(world)

    assert report.stopped
    assert creates(world) == []


def test_a_dry_run_does_not_list_what_a_hold_records_by_id(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    change = hand_made(world, "change", "Remember lanes")
    group = hand_made(world, "group", PERSON_TITLE, change.id)
    hold_with(world, {"change": change.id, "group": group.id})

    report = reconcile(
        "app",
        changes_dir=world.changes_dir,
        changes=[CHANGE],
        units=[],
        browse=browse_example,
        state_dir=world.state_dir,
        log=world.logs.append,
        dry_run=True,
    )

    assert report.listed == (f"{CHANGE}:2",)
    assert world.tracker.writes() == []


def test_an_id_another_board_mapped_is_not_mapped_elsewhere(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    write_change(world.changes_dir, OTHER)
    taken = hand_made(world, "change", "Remember lanes")
    write_tracker(
        world.changes_dir / OTHER,
        TrackerFile(kind=world.section.kind, target="another board", change=Synced(id=taken.id)),
    )
    hold_with(world, {"change": taken.id})

    report = run(world)

    assert report.conflicts == ()
    mapping = recorded(world)
    assert mapping.change is not None and mapping.change.id == taken.id


def test_an_id_of_the_wrong_type_is_a_conflict_and_nothing_is_adopted_or_created(
    tmp_path: Path,
) -> None:
    world = world_for(tmp_path, ["change", "group"])
    change = hand_made(world, "change", "Remember lanes")
    wrong = hand_made(world, "change", "A change-level item", change.id)
    hold_with(world, {"change": change.id, "group": wrong.id})

    report = run(world)

    assert named(report, wrong.id)
    assert f"{CHANGE}:1" not in recorded(world).groups
    assert ("group", f"{CHANGE}:1") not in creates(world)


def test_a_task_under_the_wrong_parent_is_a_conflict_and_not_adopted(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group", "task"])
    change = hand_made(world, "change", "Remember lanes")
    group = hand_made(world, "group", PERSON_TITLE, change.id)
    elsewhere = hand_made(world, "group", "Somebody else's group", change.id)
    stray = hand_made(world, "task", "Gap fill", elsewhere.id)
    hold_with(world, {"change": change.id, "group": group.id, "tasks": [stray.id]})

    report = run(world)

    assert named(report, stray.id)
    assert f"{CHANGE}:1.1" not in recorded(world).tasks


def test_an_item_mapped_to_another_change_is_a_conflict_naming_both(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    write_change(world.changes_dir, OTHER)
    taken = hand_made(world, "change", "The other change")
    write_tracker(
        world.changes_dir / OTHER,
        TrackerFile(
            kind=world.section.kind,
            target=mapping_target(world.section),
            change=Synced(id=taken.id),
        ),
    )
    hold_with(world, {"change": taken.id})

    report = run(world)

    assert named(report, CHANGE, OTHER)
    mapping = recorded(world)
    assert mapping.change is None or mapping.change.id != taken.id
    assert ("change", CHANGE) not in creates(world)


def test_an_id_that_no_longer_exists_is_a_conflict_not_a_silent_create(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    change = hand_made(world, "change", "Remember lanes")
    hold_with(world, {"change": change.id, "group": "999"})

    report = run(world)

    assert named(report, "999")
    assert ("group", f"{CHANGE}:1") not in creates(world)
    assert f"{CHANGE}:1" not in recorded(world).groups


def test_a_change_item_with_no_recorded_ids_is_adopted_by_its_marker(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    marker = f"<!-- {world.section.marker_prefix}:{CHANGE} -->"
    change = hand_made(world, "change", PERSON_TITLE, body=f"by hand\n{marker}", markers=(CHANGE,))
    hold_with(world, {})

    run(world)

    mapping = recorded(world)
    assert mapping.change is not None and mapping.change.id == change.id
    assert ("change", CHANGE) not in creates(world)
    assert world.tracker.get(change.id).title == PERSON_TITLE


def test_a_group_item_covering_several_groups_goes_to_the_lowest_with_a_conflict_for_the_rest(
    tmp_path: Path,
) -> None:
    world = world_for(tmp_path, ["change", "group"])
    change = hand_made(world, "change", "Remember lanes")
    both = hand_made(world, "group", PERSON_TITLE, change.id)
    hold_with(world, {"change": change.id, "group": both.id}, scope=(1, 2))

    report = run(world, 1, 2)

    assert recorded(world).groups[f"{CHANGE}:1"].id == both.id
    assert named(report, f"{CHANGE}:2")
    assert recorded(world).groups.get(f"{CHANGE}:2", Synced(id="")).id != both.id
