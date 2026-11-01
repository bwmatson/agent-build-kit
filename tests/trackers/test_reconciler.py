"""The reconciler: the wanted board pushed to the tracker, only where it differs."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import telemetry, trackers
from agent_build_kit.forges.transport import AuthError, RateLimited
from agent_build_kit.pipeline.tracker_file import read_tracker
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.trackers.local import LocalTracker
from tests.trackers.board_support import CHANGE, board_section, covering
from tests.trackers.reconciler_support import READS, SYNC, Call, RecordingTracker, World


def groups_tasks(count: int) -> str:
    """A `tasks.md` of `count` groups, each with a test task and an implementation task."""
    parts = ["# Remember lanes between runs\n"]
    for number in range(1, count + 1):
        parts.append(
            f"## {number}. [app] [unit-test] Group {number} work\n\n"
            f"- [ ] {number}.1 Test: `tests/lanes/test_{number}.py` — it works. Verify: red.\n"
            f"- [ ] {number}.2 Add the work in `src/app/lanes_{number}.py`. "
            f"Verify: {number}.1 passes.\n"
        )
    return "\n".join(parts)


def world_for(tmp_path: Path, levels: list[str], *, epic: bool = False) -> World:
    return World(tmp_path, board_section(levels, epic=epic), RecordingTracker())


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


@pytest.fixture
def errors_counted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    names: list[str] = []
    monkeypatch.setattr(telemetry, "count", lambda name, *args, **kwargs: names.append(name))
    return names


def creates(world: World) -> list[tuple[str, str]]:
    """The kind and marker of each create, in the order they were made."""
    return [(call.args[0], call.kwargs["markers"][0]) for call in world.tracker.made("create")]


def test_a_first_run_creates_the_board_in_dependency_order_and_records_each_id(
    tmp_path: Path,
) -> None:
    world = world_for(tmp_path, ["change", "group", "task"])

    report = world.run()

    assert creates(world) == [
        ("change", CHANGE),
        ("group", f"{CHANGE}:1"),
        ("group", f"{CHANGE}:2"),
        ("task", f"{CHANGE}:1.1"),
        ("task", f"{CHANGE}:1.2"),
        ("task", f"{CHANGE}:2.1"),
        ("task", f"{CHANGE}:2.2"),
    ]
    assert report.created == 7
    recorded = read_tracker(world.change_dir)
    assert recorded is not None
    assert recorded.change is not None
    assert recorded.change.id == world.item_id(CHANGE)
    assert {key: entry.id for key, entry in recorded.groups.items()} == {
        f"{CHANGE}:1": world.item_id(f"{CHANGE}:1"),
        f"{CHANGE}:2": world.item_id(f"{CHANGE}:2"),
    }
    assert {key: entry.id for key, entry in recorded.tasks.items()} == {
        f"{CHANGE}:{group}.{task}": world.item_id(f"{CHANGE}:{group}.{task}")
        for group in (1, 2)
        for task in (1, 2)
    }
    parents = {call.kwargs["markers"][0]: call.args[3] for call in world.tracker.made("create")}
    assert parents[CHANGE] is None
    assert parents[f"{CHANGE}:2"] == world.item_id(CHANGE)
    assert parents[f"{CHANGE}:2.1"] == world.item_id(f"{CHANGE}:2")


def test_the_change_item_is_made_by_the_sync_identity_and_nothing_is_assigned(
    tmp_path: Path,
) -> None:
    world = world_for(tmp_path, ["change", "group", "task"])

    world.run()

    change_item = world.tracker.find_by_marker(CHANGE)
    assert change_item is not None
    made_by = {
        change.who
        for change in world.tracker.changed_since(None)[0]
        if change.item_id == change_item.id and "created" in change.fields
    }
    assert made_by == {SYNC}
    assert not world.tracker.made("set_assignee")
    assert not world.tracker.made("claim")
    for marker in (f"{CHANGE}:1", f"{CHANGE}:1.1"):
        item = world.tracker.find_by_marker(marker)
        assert item is not None
        assert item.assignees == ()


def test_the_epic_item_gets_only_reads(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"], epic=True)
    epic = world.tracker.add_epic("The epic")
    world.record_epic(epic.id)

    world.run([covering(f"{CHANGE}/1", (1, 2), UnitState.RUNNING)])
    world.run([covering(f"{CHANGE}/1", (1, 2), UnitState.IN_REVIEW)])

    change_item = world.tracker.find_by_marker(CHANGE)
    assert change_item is not None
    assert change_item.parent_id == epic.id
    on_epic = [
        call
        for call in world.tracker.calls
        if call.name != "create" and call.args and call.args[0] == epic.id
    ]
    assert all(call.name in READS for call in on_epic)
    assert world.tracker.get(epic.id).revision == epic.revision


def test_a_second_run_makes_only_reads(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group", "task"])
    world.run()
    world.tracker.calls.clear()

    report = world.run()

    assert world.tracker.writes() == []
    assert (report.created, report.updated) == (0, 0)


def test_a_state_change_makes_one_update_per_group_item_the_unit_covers(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    world.run([covering(f"{CHANGE}/1", (1, 2), UnitState.RUNNING)])
    world.tracker.calls.clear()

    report = world.run([covering(f"{CHANGE}/1", (1, 2), UnitState.IN_REVIEW)])

    group_ids = {
        world.tracker.find_by_marker(f"{CHANGE}:{group}").id  # type: ignore[union-attr]
        for group in (1, 2)
    }
    updates = world.tracker.made("update")
    assert {call.args[0] for call in updates} == group_ids
    assert len(updates) == 2
    assert report.updated == 2
    for call in updates:
        assert len(call.args[1]) == 1, "only the tag changes"
        assert any("in-review" in value for value in call.args[1].values())
        assert call.args[2] is not None, "the update names the revision it was computed against"
    assert [call.name for call in world.tracker.writes()] == ["update", "update"]


def test_an_item_changed_on_the_board_is_left_for_the_inbound_sync(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    world.run([covering(f"{CHANGE}/1", (1,), UnitState.RUNNING)])
    edited = world.tracker.find_by_marker(f"{CHANGE}:1")
    assert edited is not None
    LocalTracker.update(world.tracker, edited.id, {"title": "Renamed on the board"})
    world.tracker.calls.clear()

    report = world.run([covering(f"{CHANGE}/1", (1,), UnitState.IN_REVIEW)])

    assert [call for call in world.tracker.writes() if call.args[0] == edited.id] == []
    assert report.awaiting == (f"{CHANGE}:1",)
    assert world.tracker.get(edited.id).title == "Renamed on the board"


@pytest.mark.parametrize("lose_tracker_file", [False, True])
def test_a_lost_snapshot_costs_reads_and_creates_nothing(
    tmp_path: Path, lose_tracker_file: bool
) -> None:
    world = world_for(tmp_path, ["change", "group", "task"])
    world.run()
    assert world.snapshot.is_file()
    world.snapshot.unlink()
    if lose_tracker_file:
        (world.change_dir / "tracker.yaml").unlink()
    world.tracker.calls.clear()

    world.run()

    assert world.tracker.made("create") == []
    assert world.tracker.writes() == []
    assert world.snapshot.is_file(), "the snapshot is rebuilt"
    recorded = read_tracker(world.change_dir)
    assert recorded is not None
    assert recorded.change is not None
    assert set(recorded.groups) == {f"{CHANGE}:1", f"{CHANGE}:2"}
    assert len(recorded.tasks) == 4


def test_a_create_whose_answer_was_lost_is_found_by_its_marker_next_time(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    world.tracker.lose_answer = CHANGE

    first = world.run()

    assert first.errors >= 1
    landed = world.tracker.find_by_marker(CHANGE)
    assert landed is not None

    world.tracker.calls.clear()
    world.run()

    assert [marker for _, marker in creates(world)] == [f"{CHANGE}:1", f"{CHANGE}:2"]
    recorded = read_tracker(world.change_dir)
    assert recorded is not None
    assert recorded.change is not None
    assert recorded.change.id == landed.id


def test_a_failing_item_is_logged_and_counted_and_the_others_go_on(
    tmp_path: Path, errors_counted: list[str]
) -> None:
    world = world_for(tmp_path, ["change", "group"])
    (world.change_dir / "tasks.md").write_text(groups_tasks(3))

    def fail_second(call: Call) -> Exception | None:
        if call.name == "create" and call.kwargs["markers"] == (f"{CHANGE}:2",):
            return ValueError("the title is refused")
        return None

    world.tracker.fail = fail_second

    report = world.run()

    assert [marker for _, marker in creates(world) if world.tracker.find_by_marker(marker)] == [
        CHANGE,
        f"{CHANGE}:1",
        f"{CHANGE}:3",
    ]
    assert report.errors == 1
    assert errors_counted == ["abk.tracker.errors"]
    assert any("the title is refused" in line and f"{CHANGE}:2" in line for line in world.logs)
    recorded = read_tracker(world.change_dir)
    assert recorded is not None
    assert set(recorded.groups) == {f"{CHANGE}:1", f"{CHANGE}:3"}


def test_a_rate_limit_ends_the_pass_and_the_next_run_continues(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    (world.change_dir / "tasks.md").write_text(groups_tasks(3))
    limited: list[bool] = []

    def after_two_creates(call: Call) -> Exception | None:
        if call.name == "create" and len(world.tracker.made("create")) == 3 and not limited:
            limited.append(True)
            return RateLimited("POST /items: rate limited", retry_after=None)
        return None

    world.tracker.fail = after_two_creates

    first = world.run()

    assert first.stopped
    assert first.created == 2
    assert len(world.tracker.made("create")) == 3, "the pass stops at the limit"

    world.tracker.calls.clear()
    second = world.run()

    assert not second.stopped
    assert [marker for _, marker in creates(world)] == [f"{CHANGE}:2", f"{CHANGE}:3"]
    assert second.created == 2


def test_a_refused_credential_is_one_logged_line_for_the_repo(
    tmp_path: Path, errors_counted: list[str]
) -> None:
    world = world_for(tmp_path, ["change", "group"])
    (world.change_dir / "tasks.md").write_text(groups_tasks(19))
    units = [covering(f"{CHANGE}/1", (1,), UnitState.RUNNING)]

    def refuse(call: Call) -> Exception | None:
        return AuthError("401: the token is refused")

    world.tracker.fail = refuse

    world.run(units)

    assert len(world.logs) == 1
    assert "app" in world.logs[0]
    assert "refused" in world.logs[0]
    assert units[0].state is UnitState.RUNNING
    assert read_tracker(world.change_dir) is None
    assert len(world.tracker.calls) <= 2, "the pass gives up on the first refusal"


def test_a_configuration_error_skips_the_repo(tmp_path: Path) -> None:
    world = world_for(tmp_path, ["change", "group"])
    trackers.unregister("azure_devops")

    report = world.run()

    assert world.tracker.calls == []
    assert (report.created, report.updated, report.errors) == (0, 0, 0)
    assert read_tracker(world.change_dir) is None
    assert list(world.state_dir.iterdir()) == []
