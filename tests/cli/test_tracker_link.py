"""`abk tracker link` adopts a person-made item for a change, a group or the change's epic
(spec: tracker-rollout).

The stand-in board reports each item's configured board type (Epic, Issue, Task and Subtask
here, none a level's name) and can mark an item as outside the board's scope."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.tracker_file import read_tracker
from tests.cli.tracker_cmd_support import BOARD_TYPES, Mirror, create_kinds, section_text
from tests.trackers.board_support import CHANGE, groups_tasks, write_change

EPIC_TITLE = "Agent Assessment: P0 Foundation"
WRITES_TO_AN_ITEM = ("update", "set_assignee", "link", "comment", "claim")


def refused(code: int, out: str, *words: str) -> None:
    assert code != 0, out
    for word in words:
        assert word.lower() in out.lower(), out


def test_a_person_made_change_item_is_adopted_and_the_next_sync_fills_under_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    issue = mirror.board.create("change", "Made by a person")

    code, out = mirror.run(capsys, "link", CHANGE, issue.id)

    assert code == 0, out
    recorded = mirror.tracker_file().change
    assert recorded is not None
    assert recorded.id == issue.id
    mirror.board.calls.clear()
    code, out = mirror.run(capsys, "sync")
    assert code == 0, out
    assert "change" not in create_kinds(mirror.board)
    assert {call.args[3] for call in mirror.board.made("create")} == {issue.id}
    assert_wording_kept(mirror, issue.id, "Made by a person")


def assert_wording_kept(mirror: Mirror, item_id: str, title: str) -> None:
    """The sync left the title and body the person wrote, and wrote neither to the item."""
    assert mirror.board.get(item_id).title == title
    assert mirror.board.get(item_id).body == ""
    written = [c for c in mirror.board.made("update") if c.args[0] == item_id]
    assert all(not {"title", "body"} & set(c.args[1]) for c in written)


def test_a_title_edit_on_a_linked_item_is_not_a_conflict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    issue = mirror.board.create("change", "Made by a person")
    code, out = mirror.run(capsys, "link", CHANGE, issue.id)
    assert code == 0, out
    code, out = mirror.run(capsys, "sync")  # the first pull only records its place
    assert code == 0, out
    mirror.board.as_identity("alice@example.test").update(issue.id, {"title": "Retitled"})

    code, out = mirror.run(capsys, "sync")

    assert code == 0, out
    assert [r for r in mirror.tracker_file().conflicts if r.status == "open"] == []
    assert mirror.board.get(issue.id).title == "Retitled"


def test_a_person_made_group_item_is_adopted_with_the_option(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    group = mirror.board.create("group", "Made by a person")

    code, out = mirror.run(capsys, "link", CHANGE, group.id, "--group", "2")

    assert code == 0, out
    assert mirror.tracker_file().groups[f"{CHANGE}:2"].id == group.id
    mirror.board.calls.clear()
    code, out = mirror.run(capsys, "sync")
    assert code == 0, out
    markers = [call.kwargs["markers"] for call in mirror.board.made("create")]
    assert (f"{CHANGE}:2",) not in markers
    assert_wording_kept(mirror, group.id, "Made by a person")


def test_an_item_of_the_wrong_type_is_refused_naming_both_types(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    epic = mirror.board.add_epic("A person's epic")

    code, out = mirror.run(capsys, "link", CHANGE, epic.id)

    refused(code, out, epic.id, "Epic", "Issue")
    assert not (mirror.change_dir / "tracker.yaml").exists()


def test_an_item_already_mapped_to_another_change_is_refused_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path, groups=1)
    write_change(mirror.changes_dir, "other-change", tasks=groups_tasks(1))
    code, out = mirror.run(capsys, "sync")
    assert code == 0, out
    held = read_tracker(mirror.changes_dir / "other-change")
    assert held is not None and held.change is not None
    (mirror.change_dir / "tracker.yaml").unlink()

    code, out = mirror.run(capsys, "link", CHANGE, held.change.id)

    refused(code, out, "other-change")
    assert not (mirror.change_dir / "tracker.yaml").exists()


def test_an_item_already_mapped_to_another_group_of_the_change_is_refused_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    group = mirror.board.create("group", "Made by a person")
    code, out = mirror.run(capsys, "link", CHANGE, group.id, "--group", "1")
    assert code == 0, out

    code, out = mirror.run(capsys, "link", CHANGE, group.id, "--group", "2")

    refused(code, out, f"{CHANGE}:1")
    assert f"{CHANGE}:2" not in mirror.tracker_file().groups


@pytest.mark.parametrize("extra", [["ITEM"], ["--group", "1"]])
def test_epic_with_an_item_id_or_a_group_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], extra: list[str]
) -> None:
    mirror = Mirror(tmp_path)

    code, out = mirror.run(capsys, "link", CHANGE, *extra, "--epic")

    refused(code, out, "--epic")


def test_a_task_item_is_refused_with_the_reason(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path, levels=("change", "group", "task"))
    task = mirror.board.create("task", "A task item")

    code, out = mirror.run(capsys, "link", CHANGE, task.id)

    refused(code, out, "tasks.md")
    assert not (mirror.change_dir / "tracker.yaml").exists()


def test_a_group_item_is_adopted_when_its_type_is_also_the_unused_task_type(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path, types={**BOARD_TYPES, "task": BOARD_TYPES["group"]})
    group = mirror.board.create("group", "Made by a person")

    code, out = mirror.run(capsys, "link", CHANGE, group.id, "--group", "1")

    assert code == 0, out
    assert mirror.tracker_file().groups[f"{CHANGE}:1"].id == group.id


def test_an_item_out_of_scope_is_refused_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    issue = mirror.board.create("change", "In another project")
    mirror.board.mark_out_of_scope(issue.id)

    code, out = mirror.run(capsys, "link", CHANGE, issue.id)

    refused(code, out, issue.id, "outside")
    assert not (mirror.change_dir / "tracker.yaml").exists()


def test_an_epic_out_of_scope_is_refused_naming_it(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    epic = mirror.board.add_epic(EPIC_TITLE)
    mirror.board.mark_out_of_scope(epic.id)
    mirror.set_epic_line(EPIC_TITLE)

    code, out = mirror.run(capsys, "link", CHANGE, "--epic")

    refused(code, out, epic.id, "outside")
    assert not (mirror.change_dir / "tracker.yaml").exists()


def test_a_group_of_another_repo_is_refused_naming_the_group_and_the_repo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path, platform=True)
    tasks = mirror.change_dir / "tasks.md"
    tasks.write_text(tasks.read_text().replace("## 2. [app]", "## 2. [platform]"))
    group = mirror.board.create("group", "Made by a person")

    code, out = mirror.run(capsys, "link", CHANGE, group.id, "--group", "2")

    refused(code, out, "group 2", "app")
    assert not (mirror.change_dir / "tracker.yaml").exists()


def test_a_group_the_change_does_not_have_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    group = mirror.board.create("group", "Made by a person")

    code, out = mirror.run(capsys, "link", CHANGE, group.id, "--group", "9")

    refused(code, out, "group 9")
    assert not (mirror.change_dir / "tracker.yaml").exists()


def test_the_epic_line_is_resolved_by_exact_title_and_recorded(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    mirror.board.add_epic(f"{EPIC_TITLE} (old)")
    epic = mirror.board.add_epic(EPIC_TITLE)
    mirror.set_epic_line(EPIC_TITLE)

    code, out = mirror.run(capsys, "link", CHANGE, "--epic")

    assert code == 0, out
    assert mirror.tracker_file().epic == epic.id


def test_the_epic_line_is_resolved_by_id(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    epic = mirror.board.add_epic(EPIC_TITLE)
    mirror.set_epic_line(epic.id)

    code, out = mirror.run(capsys, "link", CHANGE, "--epic")

    assert code == 0, out
    assert mirror.tracker_file().epic == epic.id


def test_the_epic_item_is_only_read_by_the_link_and_a_following_sync(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    epic = mirror.board.add_epic(EPIC_TITLE)
    mirror.set_epic_line(EPIC_TITLE)

    code, out = mirror.run(capsys, "link", CHANGE, "--epic")
    assert code == 0, out
    code, out = mirror.run(capsys, "sync")
    assert code == 0, out

    on_epic = [
        c for c in mirror.board.calls if c.name in WRITES_TO_AN_ITEM and c.args[0] == epic.id
    ]
    assert on_epic == []
    change_creates = [c for c in mirror.board.made("create") if c.args[0] == "change"]
    assert [c.args[3] for c in change_creates] == [epic.id]


def test_a_change_with_no_epic_line_is_refused_and_nothing_is_written(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path)
    mirror.board.add_epic(EPIC_TITLE)

    code, out = mirror.run(capsys, "link", CHANGE, "--epic")

    refused(code, out, "Epic:")
    assert not (mirror.change_dir / "tracker.yaml").exists()


def test_a_repo_with_no_epic_setting_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path, section=section_text().replace("epic: true", "epic: false"))
    mirror.set_epic_line(EPIC_TITLE)

    code, out = mirror.run(capsys, "link", CHANGE, "--epic")

    refused(code, out, "epic")
    assert not (mirror.change_dir / "tracker.yaml").exists()
