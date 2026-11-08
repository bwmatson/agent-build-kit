"""`abk tracker conflicts` lists open conflicts and marks them resolved once the sides agree, and
every `abk tracker` command is a no-op without a section (spec: tracker-rollout)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.tracker_file import (
    ConflictRecord,
    Synced,
    read_tracker,
    write_tracker,
)
from agent_build_kit.trackers.folders import ARCHIVED_TRACKERS
from tests.cli.tracker_cmd_support import APP, NONE_CONFIGURED, Mirror
from tests.trackers.board_support import CHANGE

BOARD_TITLE = "A title a person chose"
COMMANDS = (
    ("status",),
    ("sync",),
    ("sync", "--dry-run"),
    ("link", CHANGE, "1"),
    ("link", CHANGE, "--epic"),
    ("conflicts",),
    ("conflicts", "--resolve", "any"),
)


def mirrored(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[Mirror, str, str]:
    """A mirror after one pass, with a person's retitle of the first group recorded as an open
    conflict; the group's item id and its title as the spec has it."""
    mirror = Mirror(tmp_path)
    code, out = mirror.run(capsys, "sync")
    assert code == 0, out
    group = mirror.board.find_by_marker(f"{CHANGE}:1")
    assert group is not None
    mirror.board.as_identity("alice@example.test").update(group.id, {"title": BOARD_TITLE})
    mirror.record_conflict(group.id, "title", group.title, BOARD_TITLE)
    return mirror, group.id, group.title


def test_open_conflicts_are_listed_with_both_values(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror, group_id, spec_title = mirrored(tmp_path, capsys)
    other = mirror.board.find_by_marker(f"{CHANGE}:2")
    assert other is not None
    extra = ConflictRecord(
        item_id=other.id, field="title", spec_value="Group 2 work", tracker_value="Another title"
    )
    recorded = mirror.tracker_file()
    write_tracker(
        mirror.change_dir,
        recorded.model_copy(update={"conflicts": (*recorded.conflicts, extra)}),
    )

    code, out = mirror.run(capsys, "conflicts")

    assert code == 0, out
    for value in (spec_title, BOARD_TITLE, "Group 2 work", "Another title"):
        assert value in out
    listed = mirror.run_json(capsys, "conflicts")["conflicts"]
    assert {c["item_id"] for c in listed} == {group_id, other.id}
    assert all(c["repo"] == APP and c["change"] == CHANGE for c in listed)


def test_resolving_refuses_while_the_sides_differ_and_shows_the_difference(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror, _, spec_title = mirrored(tmp_path, capsys)
    (conflict,) = mirror.run_json(capsys, "conflicts")["conflicts"]

    code, out = mirror.run(capsys, "conflicts", "--resolve", conflict["id"])

    assert code != 0, out
    assert spec_title in out
    assert BOARD_TITLE in out
    assert [r.status for r in mirror.tracker_file().conflicts] == ["open"]


def test_resolving_marks_the_conflict_resolved_once_the_board_text_matches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror, group_id, spec_title = mirrored(tmp_path, capsys)
    (conflict,) = mirror.run_json(capsys, "conflicts")["conflicts"]
    mirror.board.as_identity("alice@example.test").update(group_id, {"title": spec_title})

    code, out = mirror.run(capsys, "conflicts", "--resolve", conflict["id"])

    assert code == 0, out
    assert [r.status for r in mirror.tracker_file().conflicts] == ["closed"]
    assert mirror.run_json(capsys, "conflicts")["conflicts"] == []


def test_resolving_closes_when_the_spec_is_edited_to_match_the_board(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror, _, spec_title = mirrored(tmp_path, capsys)
    (conflict,) = mirror.run_json(capsys, "conflicts")["conflicts"]
    tasks = mirror.change_dir / "tasks.md"
    tasks.write_text(tasks.read_text().replace(spec_title, BOARD_TITLE))

    code, out = mirror.run(capsys, "conflicts", "--resolve", conflict["id"])

    assert code == 0, out
    assert [r.status for r in mirror.tracker_file().conflicts] == ["closed"]


def test_resolving_refuses_when_the_board_returns_to_a_value_the_spec_no_longer_has(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror, group_id, spec_title = mirrored(tmp_path, capsys)
    (conflict,) = mirror.run_json(capsys, "conflicts")["conflicts"]
    tasks = mirror.change_dir / "tasks.md"
    tasks.write_text(tasks.read_text().replace(spec_title, "A third title"))
    mirror.board.as_identity("alice@example.test").update(group_id, {"title": spec_title})

    code, out = mirror.run(capsys, "conflicts", "--resolve", conflict["id"])

    assert code != 0, out
    assert "A third title" in out
    assert [r.status for r in mirror.tracker_file().conflicts] == ["open"]


def test_a_state_conflict_resolves_when_the_boards_word_differs_from_the_kits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path, levels=("change", "group", "task"))
    code, out = mirror.run(capsys, "sync")
    assert code == 0, out
    task = mirror.board.find_by_marker(f"{CHANGE}:1.1")
    assert task is not None
    tasks = mirror.change_dir / "tasks.md"
    tasks.write_text(tasks.read_text().replace("- [ ] 1.1", "- [x] 1.1"))
    mirror.board.show_board_state(task.id, "Done", "done")
    mirror.record_conflict(task.id, "state", "done", "new")
    (conflict,) = mirror.run_json(capsys, "conflicts")["conflicts"]

    code, out = mirror.run(capsys, "conflicts", "--resolve", conflict["id"])

    assert code == 0, out
    assert [r.status for r in mirror.tracker_file().conflicts] == ["closed"]


def test_a_removed_conflict_resolves_when_the_item_is_back_on_the_board(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror, group_id, _ = mirrored(tmp_path, capsys)
    mirror.record_conflict(group_id, "removed", "", "removed")
    mirror.board.show_board_state(group_id, "Removed", "removed")
    (conflict,) = mirror.run_json(capsys, "conflicts")["conflicts"]
    code, out = mirror.run(capsys, "conflicts", "--resolve", conflict["id"])
    assert code != 0, out

    mirror.board.show_board_state(group_id, "To Do", "new")
    code, out = mirror.run(capsys, "conflicts", "--resolve", conflict["id"])

    assert code == 0, out
    assert [r.status for r in mirror.tracker_file().conflicts] == ["closed"]


def test_a_closed_conflict_resolves_once_the_item_is_reopened_on_the_board(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror, group_id, _ = mirrored(tmp_path, capsys)
    mirror.record_conflict(group_id, "closed", "", "done")
    mirror.board.show_board_state(group_id, "Done", "done")
    (conflict,) = [
        row for row in mirror.run_json(capsys, "conflicts")["conflicts"] if row["field"] == "closed"
    ]
    code, out = mirror.run(capsys, "conflicts", "--resolve", conflict["id"])
    assert code != 0, out
    assert "done" in out and "unmerged" in out

    mirror.board.show_board_state(group_id, "To Do", "new")
    code, out = mirror.run(capsys, "conflicts", "--resolve", conflict["id"])

    assert code == 0, out
    assert [r.status for r in mirror.tracker_file().conflicts if r.field == "closed"] == ["closed"]


def test_resolving_an_archived_change_keeps_the_local_copys_other_entries(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror, group_id, spec_title = mirrored(tmp_path, capsys)
    recorded = mirror.tracker_file()
    committed = mirror.changes_dir / "archive" / f"2026-01-01-{CHANGE}"
    committed.parent.mkdir()
    mirror.change_dir.rename(committed)
    # The machine-local copy has an entry the committed one lacks, and wins over it.
    local = mirror.root / ARCHIVED_TRACKERS / committed.name
    local.mkdir(parents=True)
    newer = {**recorded.groups, f"{CHANGE}:3": Synced(id="99")}
    write_tracker(local, recorded.model_copy(update={"groups": newer}))
    mirror.board.as_identity("alice@example.test").update(group_id, {"title": spec_title})
    (conflict,) = mirror.run_json(capsys, "conflicts")["conflicts"]

    code, out = mirror.run(capsys, "conflicts", "--resolve", conflict["id"])

    assert code == 0, out
    kept = read_tracker(local)
    assert kept is not None
    assert f"{CHANGE}:3" in kept.groups
    assert [r.status for r in kept.conflicts] == ["closed"]


@pytest.mark.parametrize("argv", COMMANDS, ids=" ".join)
def test_every_command_is_a_no_op_without_a_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], argv: tuple[str, ...]
) -> None:
    mirror = Mirror(tmp_path, section="")
    before = mirror.files()

    code, out = mirror.run(capsys, *argv)

    assert code == 0, out
    assert NONE_CONFIGURED in out
    assert mirror.files() == before
    assert mirror.board.calls == []


@pytest.mark.parametrize("command", ["status", "conflicts"])
def test_the_json_form_without_a_section_is_one_document(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], command: str
) -> None:
    mirror = Mirror(tmp_path, section="")

    document = mirror.run_json(capsys, command)

    assert isinstance(document, dict)
    assert json.dumps(document)
