"""The wanted board: what the kit wants on the tracker, computed from the planning state alone."""

from __future__ import annotations

from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit import trackers
from agent_build_kit.pipeline.units import Unit, UnitState
from agent_build_kit.trackers.config import TrackerSection, section_for
from agent_build_kit.trackers.wanted_board import WantedItem, wanted_board
from tests.factories import unit as make_unit
from tests.trackers.tracker_section_support import AZURE_BLOCK, configure

CHANGE = "lane-dedupe"
REPO_URL = "https://example.test/example/app/tree/main"
TYPES = {"epic": "Epic", "change": "Feature", "group": "Product Backlog Item", "task": "Task"}

PROPOSAL = """\
## Why

Lanes are filled twice when a rerun starts.

## What Changes

- The fill remembers the lanes it has seen.

## Impact

Nothing outside the fill.
"""
DESIGN = """\
## Context

Background nobody needs on the board.

## Decisions

**Remember lanes by key.** A lane is remembered under its key, and the first fill wins.
See docs/designs/lane-design.md#remembered-lanes for the longer argument.

## Risks

A risk nobody needs on the board.
"""
SPEC = """\
## ADDED Requirements

### Requirement: A lane is filled once

The fill SHALL fill each lane once.

#### Scenario: a rerun fills nothing (unit)

- **GIVEN** a filled lane
- **WHEN** the fill runs again
- **THEN** nothing is written

### Requirement: Conflicts are reported

A conflict SHALL be reported.

#### Scenario: a conflict is named (unit)

- **GIVEN** two lanes with one key
- **WHEN** the fill runs
- **THEN** the conflict is named
"""
TASKS = """\
# Remember lanes between runs

## 1. [app] [unit-test] Gap fill, conflicts and remembered lanes

Needs: base-change group 2 merged — the lane table

- [x] 1.1 Test: `tests/lanes/test_gap.py` — a gap is filled once. Verify: red.
- [ ] 1.2 Add the fill in `src/app/lanes.py`. Verify: 1.1 passes.

## 2. [app] [e2e-test] Report the lanes

- [ ] 2.1 Test: `tests/e2e/test_report.py` — the report lists each lane. Verify: red.
- [ ] 2.2 Add the report in `src/app/report.py`. Verify: 2.1 passes.
"""


def board_section(levels: Sequence[str], *, epic: bool = False) -> TrackerSection:
    configure(
        app={
            "kind": "azure_devops",
            "levels": list(levels),
            "epic": epic,
            "azure_devops": {**AZURE_BLOCK, "types": TYPES},
        }
    )
    section = section_for("app")
    assert section is not None
    return section


def write_change(
    changes_dir: Path,
    name: str = CHANGE,
    *,
    proposal: str = PROPOSAL,
    design: str = DESIGN,
    spec: str = SPEC,
    tasks: str = TASKS,
) -> None:
    folder = changes_dir / name
    (folder / "specs" / "lanes").mkdir(parents=True)
    (folder / "proposal.md").write_text(proposal)
    (folder / "design.md").write_text(design)
    (folder / "specs" / "lanes" / "spec.md").write_text(spec)
    (folder / "tasks.md").write_text(tasks)


def board(
    section: TrackerSection,
    changes_dir: Path,
    units: Sequence[Unit] = (),
    *,
    changes: Sequence[str] = (CHANGE,),
    epics: Mapping[str, str] | None = None,
) -> dict[str, WantedItem]:
    items = wanted_board(section, changes_dir, changes, units, repo_url=REPO_URL, epics=epics)
    found = {item.marker: item for item in items}
    assert len(found) == len(items), "a marker names one item"
    return found


def covering(uid: str, groups: tuple[int, ...], state: UnitState = UnitState.PLANNED) -> Unit:
    return make_unit(uid, change=CHANGE, groups=groups, state=state)


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
    assert "- [ ] 1.2 Add the fill in `src/app/lanes.py`. Verify: 1.1 passes." in first
    assert "Needs: base-change group 2 merged — the lane table" in first
    assert "tests/lanes/test_gap.py" in first
    assert "unit-test" in first
    second = found[f"{CHANGE}:2"].body
    assert "tests/e2e/test_report.py" in second
    assert "e2e-test" in second
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
