"""The wanted board: what the kit wants on the tracker, computed from the planning state alone."""

from __future__ import annotations

from collections.abc import Collection, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import config as config_module
from agent_build_kit import trackers
from agent_build_kit.pipeline.units import Unit, UnitState
from agent_build_kit.trackers.config import TrackerSection
from agent_build_kit.trackers.wanted_board import WantedItem, wanted_board
from tests.factories import unit as make_unit
from tests.trackers.board_support import (
    CHANGE,
    DESIGN,
    PROPOSAL,
    REPO_URL,
    TASKS,
    board_section,
    browse_example,
    covering,
    write_change,
)


def board(
    section: TrackerSection,
    changes_dir: Path,
    units: Sequence[Unit] = (),
    *,
    changes: Sequence[str] = (CHANGE,),
    epics: Mapping[str, str] | None = None,
    archived: Collection[str] = (),
    tracking_dir: Path | None = None,
) -> dict[str, WantedItem]:
    items = wanted_board(
        section,
        changes_dir,
        changes,
        units,
        browse=browse_example,
        epics=epics,
        archived=archived,
        tracking_dir=tracking_dir,
    )
    found = {item.marker: item for item in items}
    assert len(found) == len(items), "a marker names one item"
    return found


@pytest.fixture
def changes_dir(tmp_path: Path) -> Path:
    path = tmp_path / "changes"
    path.mkdir()
    write_change(path)
    return path


def test_a_basic_board_has_a_change_item_and_group_items(changes_dir: Path) -> None:
    found = board(
        board_section(["change", "group"]),
        changes_dir,
        [covering(f"{CHANGE}/1", (1,)), covering(f"{CHANGE}/2", (2,))],
    )

    assert set(found) == {CHANGE, f"{CHANGE}:1", f"{CHANGE}:2"}
    assert found[CHANGE].level == "change"
    assert found[CHANGE].parent_marker is None
    for group in (1, 2):
        assert found[f"{CHANGE}:{group}"].level == "group"
        assert found[f"{CHANGE}:{group}"].parent_marker == CHANGE


def test_a_three_level_board_puts_each_task_under_its_group(changes_dir: Path) -> None:
    found = board(board_section(["change", "group", "task"]), changes_dir)

    assert set(found) == {
        CHANGE,
        f"{CHANGE}:1",
        f"{CHANGE}:2",
        f"{CHANGE}:1.1",
        f"{CHANGE}:1.2",
        f"{CHANGE}:2.1",
        f"{CHANGE}:2.2",
    }
    for marker, group in ((f"{CHANGE}:1.2", 1), (f"{CHANGE}:2.1", 2)):
        assert found[marker].level == "task"
        assert found[marker].parent_marker == f"{CHANGE}:{group}"


def test_a_task_hangs_under_the_change_when_group_is_not_a_level(changes_dir: Path) -> None:
    found = board(board_section(["change", "task"]), changes_dir)

    assert set(found) == {
        CHANGE,
        *(f"{CHANGE}:{group}.{task}" for group in (1, 2) for task in (1, 2)),
    }
    assert found[f"{CHANGE}:2.1"].parent_marker == CHANGE


def test_a_tasks_state_follows_its_box(changes_dir: Path) -> None:
    found = board(board_section(["change", "group", "task"]), changes_dir)

    assert found[f"{CHANGE}:1.1"].state == "done"
    assert found[f"{CHANGE}:1.2"].state == "new"


def test_a_unit_that_builds_two_groups_gives_both_items_its_state(changes_dir: Path) -> None:
    found = board(
        board_section(["change", "group"]),
        changes_dir,
        [covering(f"{CHANGE}/1", (1, 2), UnitState.RUNNING)],
    )

    assert {marker for marker in found if ":" in marker} == {f"{CHANGE}:1", f"{CHANGE}:2"}
    assert found[f"{CHANGE}:1"].state == found[f"{CHANGE}:2"].state == "active"


@pytest.mark.parametrize(
    ("state", "wanted_state", "tags"),
    [
        (UnitState.PLANNED, "new", ()),
        (UnitState.RUNNING, "active", ()),
        (UnitState.IN_REVIEW, "active", ("in-review",)),
        (UnitState.MERGED, "done", ()),
        (UnitState.FAILED, "active", ("blocked",)),
        (UnitState.HELD, "active", ("blocked",)),
        (UnitState.RETIRED, "removed", ()),
        (UnitState.SETTLING, "done", ()),
        (UnitState.SATISFIED, "done", ()),
        (UnitState.CLOSED, "removed", ()),
        (UnitState.UNPLANNED, "removed", ()),
    ],
)
def test_a_units_state_maps_to_its_group_items_state_and_tags(
    changes_dir: Path, state: UnitState, wanted_state: str, tags: tuple[str, ...]
) -> None:
    found = board(
        board_section(["change", "group"]),
        changes_dir,
        [covering(f"{CHANGE}/1", (1,), state)],
    )

    assert found[f"{CHANGE}:1"].state == wanted_state
    assert found[f"{CHANGE}:1"].tags == tags


def test_a_group_no_unit_covers_is_new_and_takes_a_units_state_once_covered(
    changes_dir: Path,
) -> None:
    section = board_section(["change", "group"])

    before = board(section, changes_dir, [covering(f"{CHANGE}/1", (1,), UnitState.IN_REVIEW)])
    after = board(
        section,
        changes_dir,
        [
            covering(f"{CHANGE}/1", (1,), UnitState.IN_REVIEW),
            covering(f"{CHANGE}/2", (2,), UnitState.RUNNING),
        ],
    )

    assert (before[f"{CHANGE}:2"].state, before[f"{CHANGE}:2"].tags) == ("new", ())
    assert after[f"{CHANGE}:2"].state == "active"


def test_the_recorded_epic_is_the_read_only_parent_of_the_change_item(tmp_path: Path) -> None:
    changes_dir = tmp_path / "changes"
    changes_dir.mkdir()
    write_change(changes_dir)
    write_change(changes_dir, "other-change")
    section = board_section(["change", "group"], epic=True)

    found = board(
        section,
        changes_dir,
        changes=(CHANGE, "other-change"),
        epics={CHANGE: "259"},
    )

    assert found[CHANGE].parent_id == "259"
    assert found[CHANGE].parent_marker is None
    assert found["other-change"].parent_id is None
    assert found["other-change"].parent_marker is None
    assert found[f"{CHANGE}:1"].parent_marker == CHANGE
    assert found[f"{CHANGE}:1"].parent_id is None
    assert {item.level for item in found.values()} == {"change", "group"}
    assert not any("259" in marker for marker in found)


def test_a_change_item_carries_what_a_person_needs_to_understand_the_change(
    changes_dir: Path,
) -> None:
    body = board(board_section(["change", "group"]), changes_dir)[CHANGE].body

    for text in (
        "Lanes are filled twice when a rerun starts.",
        "The fill remembers the lanes it has seen.",
        "**Remember lanes by key.** A lane is remembered under its key, and the first fill wins.",
        "A lane is filled once",
        "a rerun fills nothing",
        "- **THEN** nothing is written",
        "Conflicts are reported",
        "a conflict is named",
        "- **THEN** the conflict is named",
        f"{REPO_URL}/openspec/changes/{CHANGE}",
        f"{REPO_URL}/docs/designs/lane-design.md#remembered-lanes",
    ):
        assert text in body
    for left_out in ("Background nobody needs", "A risk nobody needs", "Nothing outside the fill"):
        assert left_out not in body


def test_a_group_item_carries_its_checklist_needs_tests_and_tier(changes_dir: Path) -> None:
    section = board_section(["change", "group"])
    found = board(section, changes_dir)

    first = found[f"{CHANGE}:1"].body
    assert "- [x] 1.1 Test: `tests/lanes/test_gap.py` — a gap is filled once. Verify: red." in first
    assert (
        "- [ ] 1.2 Add the fill in `src/app/lanes.py`, covered by `tests/lanes/test_conflict.py`."
        in first
    )
    assert "      Verify: 1.1 passes." in first
    assert "Needs: base-change group 2 merged — the lane table" in first
    # The test files the tasks name, on a line of their own: a wrapped task is read to its end
    # and a source path is not a test file.
    assert "Tests: tests/lanes/test_gap.py, tests/lanes/test_conflict.py\n" in first
    assert "Tier: unit-test" in first
    second = found[f"{CHANGE}:2"].body
    assert "Tests: tests/e2e/test_report.py\n" in second
    assert "Tier: e2e-test" in second
    assert "Needs:" not in second


def test_an_edit_to_one_group_changes_only_that_groups_item(changes_dir: Path) -> None:
    section = board_section(["change", "group", "task"])
    before = board(section, changes_dir)

    write_edited = TASKS.replace("the report lists each lane", "the report lists each lane once")
    (changes_dir / CHANGE / "tasks.md").write_text(write_edited)
    after = board(section, changes_dir)

    changed = {marker for marker in before if before[marker] != after[marker]}
    assert changed == {f"{CHANGE}:2", f"{CHANGE}:2.1"}
    assert before[f"{CHANGE}:2"].body != after[f"{CHANGE}:2"].body
    assert before[CHANGE].body == after[CHANGE].body


def test_an_edit_to_the_proposal_changes_only_the_change_item(changes_dir: Path) -> None:
    section = board_section(["change", "group"])
    before = board(section, changes_dir)

    (changes_dir / CHANGE / "proposal.md").write_text(PROPOSAL.replace("twice", "three times"))
    after = board(section, changes_dir)

    assert {marker for marker in before if before[marker] != after[marker]} == {CHANGE}


def test_a_childs_title_does_not_repeat_its_parents_name(changes_dir: Path) -> None:
    found = board(board_section(["change", "group", "task"]), changes_dir)

    change, group, task = found[CHANGE], found[f"{CHANGE}:1"], found[f"{CHANGE}:1.1"]
    assert change.title == "Remember lanes between runs"
    assert group.title == "Gap fill, conflicts and remembered lanes"
    assert task.title.endswith(
        "Test: `tests/lanes/test_gap.py` — a gap is filled once. Verify: red."
    )
    for child in (group, task):
        assert CHANGE not in child.title
        assert change.title not in child.title
    assert group.title not in task.title


def test_the_items_come_outermost_level_first(changes_dir: Path) -> None:
    items = wanted_board(
        board_section(["change", "group", "task"]),
        changes_dir,
        [CHANGE],
        [],
        browse=browse_example,
    )

    assert [item.level for item in items] == ["change", "group", "group"] + ["task"] * 4


def group_state(changes_dir: Path, units: Sequence[Unit]) -> tuple[str, tuple[str, ...]]:
    item = board(board_section(["change", "group"]), changes_dir, units)[f"{CHANGE}:1"]
    return item.state, item.tags


@pytest.mark.parametrize(
    ("states", "wanted"),
    [
        ((UnitState.RUNNING, UnitState.MERGED), ("active", ())),
        ((UnitState.RUNNING, UnitState.CLOSED), ("active", ())),
        ((UnitState.IN_REVIEW, UnitState.RETIRED), ("active", ("in-review",))),
        ((UnitState.MERGED, UnitState.CLOSED), ("done", ())),
        ((UnitState.PLANNED, UnitState.MERGED), ("new", ())),
        ((UnitState.HELD, UnitState.RUNNING), ("active", ())),
        ((UnitState.CLOSED, UnitState.RETIRED), ("removed", ())),
    ],
)
def test_units_that_share_a_group_give_the_same_state_in_either_order(
    changes_dir: Path, states: tuple[UnitState, UnitState], wanted: tuple[str, tuple[str, ...]]
) -> None:
    units = [covering(f"{CHANGE}/{n}", (1,), state) for n, state in enumerate(states, start=3)]

    assert group_state(changes_dir, units) == wanted
    assert group_state(changes_dir, units[::-1]) == wanted


def test_a_superseded_unit_alone_is_removed_and_its_successor_takes_over(
    changes_dir: Path,
) -> None:
    old = make_unit(
        f"{CHANGE}/1",
        change=CHANGE,
        groups=(1, 2),
        state=UnitState.PLANNED,
        superseded_by=(f"{CHANGE}/3",),
    )
    successor = covering(f"{CHANGE}/3", (1,), UnitState.RUNNING)

    assert group_state(changes_dir, [old]) == ("removed", ())
    assert group_state(changes_dir, [old, successor]) == ("active", ())
    # Group 2 has only the superseded unit left: it is removed, not new.
    section = board_section(["change", "group"])
    assert board(section, changes_dir, [old, successor])[f"{CHANGE}:2"].state == "removed"


def change_state(changes_dir: Path, units: Sequence[Unit], *, archived: bool = False) -> str:
    section = board_section(["change", "group"])
    found = board(section, changes_dir, units, archived=(CHANGE,) if archived else ())
    return found[CHANGE].state


def test_a_change_item_is_new_until_a_unit_starts_and_active_after(changes_dir: Path) -> None:
    assert change_state(changes_dir, []) == "new"
    assert change_state(changes_dir, [covering(f"{CHANGE}/1", (1,))]) == "new"
    assert change_state(changes_dir, [covering(f"{CHANGE}/1", (1,), UnitState.RUNNING)]) == "active"


def test_a_change_item_is_done_only_when_every_group_is_merged_and_it_is_archived(
    changes_dir: Path,
) -> None:
    merged = [covering(f"{CHANGE}/1", (1, 2), UnitState.MERGED)]
    partly = [covering(f"{CHANGE}/1", (1,), UnitState.MERGED)]

    assert change_state(changes_dir, merged) == "active"
    assert change_state(changes_dir, merged, archived=True) == "done"
    assert change_state(changes_dir, partly, archived=True) == "active"


def test_a_removed_group_does_not_keep_an_archived_change_open(changes_dir: Path) -> None:
    units = [
        covering(f"{CHANGE}/1", (1,), UnitState.MERGED),
        covering(f"{CHANGE}/2", (2,), UnitState.RETIRED),
    ]

    assert change_state(changes_dir, units) == "active"
    assert change_state(changes_dir, units, archived=True) == "done"


def test_a_change_with_no_tasks_file_is_titled_from_its_proposal(tmp_path: Path) -> None:
    changes_dir = tmp_path / "changes"
    changes_dir.mkdir()
    write_change(changes_dir)
    (changes_dir / "idea").mkdir()
    (changes_dir / "idea" / "proposal.md").write_text("# Try an idea\n\n## Why\n\nBecause.\n")

    found = board(board_section(["change", "group", "task"]), changes_dir, changes=(CHANGE, "idea"))

    assert found["idea"].title == "Try an idea"
    assert found["idea"].state == "new"
    assert {marker for marker in found if marker.startswith("idea")} == {"idea"}
    assert f"{CHANGE}:1" in found


def test_the_folder_link_follows_the_configured_specs_folder(changes_dir: Path) -> None:
    current = config_module.active()
    planning = current.planning.model_copy(update={"specs_dir": "specs"})
    config_module.activate(
        current.model_copy(update={"planning": planning}), config_module.active_root()
    )

    body = board(board_section(["change", "group"]), changes_dir)[CHANGE].body

    assert f"{REPO_URL}/specs/changes/{CHANGE}" in body
    assert "openspec/changes" not in body


def test_a_host_with_no_address_leaves_the_links_out(changes_dir: Path) -> None:
    items = wanted_board(
        board_section(["change", "group"]),
        changes_dir,
        [CHANGE],
        [],
        browse=lambda path: "",
    )

    body = items[0].body
    assert "Change folder" not in body
    assert "Design:" not in body
    assert "Remember lanes by key" in body


def test_the_links_are_the_hosts_own_addresses(changes_dir: Path) -> None:
    azure = "https://dev.azure.com/acme/Proj/_git/repo"
    items = wanted_board(
        board_section(["change", "group"]),
        changes_dir,
        [CHANGE],
        [],
        browse=lambda path: f"{azure}?path=/{path}&version=GBmain",
    )

    body = items[0].body
    assert f"Change folder: {azure}?path=/openspec/changes/{CHANGE}&version=GBmain" in body
    assert (
        f"Design: {azure}?path=/docs/designs/lane-design.md&version=GBmain#remembered-lanes" in body
    )


def test_a_design_link_is_found_in_any_folder_and_a_url_is_not_one(tmp_path: Path) -> None:
    changes_dir = tmp_path / "changes"
    changes_dir.mkdir()
    design = DESIGN.replace(
        "docs/designs/lane-design.md#remembered-lanes",
        "documentation/adr/lanes.md#remembered-lanes and https://other.test/a/b.md",
    )
    write_change(changes_dir, design=design)

    body = board(board_section(["change", "group"]), changes_dir)[CHANGE].body

    assert f"Design: {REPO_URL}/documentation/adr/lanes.md#remembered-lanes" in body
    assert body.count("Design: ") == 1


def test_a_box_ticked_in_the_tracking_copy_makes_the_task_done(
    changes_dir: Path, tmp_path: Path
) -> None:
    section = board_section(["change", "group", "task"])
    tracking = tmp_path / "state" / "changes"
    (tracking / CHANGE).mkdir(parents=True)
    (tracking / CHANGE / "tasks.md").write_text(TASKS.replace("- [ ] 2.1", "- [x] 2.1"))
    before = board(section, changes_dir)

    after = board(section, changes_dir, tracking_dir=tracking)

    assert before[f"{CHANGE}:2.1"].state == "new"
    assert after[f"{CHANGE}:2.1"].state == "done"
    assert after[f"{CHANGE}:2.2"].state == "new"
    assert after[f"{CHANGE}:2"] == before[f"{CHANGE}:2"]


def test_a_change_with_no_tracking_copy_takes_its_boxes_from_the_repository_file(
    changes_dir: Path, tmp_path: Path
) -> None:
    found = board(
        board_section(["change", "group", "task"]), changes_dir, tracking_dir=tmp_path / "none"
    )

    assert found[f"{CHANGE}:1.1"].state == "done"
    assert found[f"{CHANGE}:1.2"].state == "new"


class FailingTracker:
    """A stand-in for the tracker that fails on any call and records that it was called."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def __getattr__(self, name: str) -> Any:
        self.calls.append(name)
        raise AssertionError(f"the computation called the tracker: {name}")


@pytest.fixture
def registered() -> Iterator[FailingTracker]:
    stand_in = FailingTracker()
    trackers.register("azure_devops", lambda section: stand_in)  # type: ignore[arg-type, return-value]
    yield stand_in
    trackers.unregister("azure_devops")


def test_the_computation_needs_no_tracker(changes_dir: Path, registered: FailingTracker) -> None:
    found = board(board_section(["change", "group", "task"]), changes_dir)

    assert len(found) == 7
    assert registered.calls == []
