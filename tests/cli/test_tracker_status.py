"""`abk tracker status` shows the mirror's state per repo (spec: tracker-rollout)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.cli.tracker_cmd_support import APP, NONE_CONFIGURED, ORGANIZATION, Mirror
from tests.cli.tracker_fakes import INCOMPLETE
from tests.trackers.board_support import CHANGE, groups_tasks
from tests.trackers.reconciler_support import SYNC

BOARD_TITLE = "A title a person chose"


def mirrored(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> tuple[Mirror, str]:
    """A mirror after one pass, with a third group not yet on the board and an open conflict on
    the first group's title; and that group's item id."""
    mirror = Mirror(tmp_path)
    code, out = mirror.run(capsys, "sync")
    assert code == 0, out
    (mirror.change_dir / "tasks.md").write_text(groups_tasks(3))
    group = mirror.board.find_by_marker(f"{CHANGE}:1")
    assert group is not None
    mirror.record_conflict(group.id, "title", group.title, BOARD_TITLE)
    return mirror, group.id


def test_a_mirrored_repo_is_summarised(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mirror, _ = mirrored(tmp_path, capsys)

    code, out = mirror.run(capsys, "status")

    assert code == 0, out
    assert ORGANIZATION in out
    assert SYNC in out
    assert BOARD_TITLE in out


def test_json_holds_the_fields_the_text_shows(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror, group_id = mirrored(tmp_path, capsys)

    repo = mirror.run_json(capsys, "status")["repos"][APP]

    assert ORGANIZATION in repo["target"]
    assert repo["identity"] == SYNC
    assert (repo["changes"], repo["groups"], repo["tasks"]) == (1, 2, 0)
    assert repo["to_create"] == 1
    assert repo["last_push"] and repo["last_pull"]
    assert [c["item_id"] for c in repo["conflicts"]] == [group_id]
    assert repo["error"] is None


def test_an_incomplete_section_is_reported_by_key_and_exits_normally(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path, section=INCOMPLETE)

    code, out = mirror.run(capsys, "status")

    assert code == 0, out
    assert "project" in out
    assert APP in out


def test_the_error_is_in_the_json_form(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    mirror = Mirror(tmp_path, section=INCOMPLETE)

    repo = mirror.run_json(capsys, "status")["repos"][APP]

    assert "project" in repo["error"]


def test_a_repo_with_no_section_prints_that_none_is_configured(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    mirror = Mirror(tmp_path, section="")

    code, out = mirror.run(capsys, "status")

    assert code == 0, out
    assert NONE_CONFIGURED in out
    assert APP in out
    assert mirror.board.calls == []
