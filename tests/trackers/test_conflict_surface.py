"""Where a person sees a conflict: one comment on the item, a line in `abk status`, and the
close when the two sides agree again (spec: tracker-pull)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

from agent_build_kit import trackers
from agent_build_kit.pipeline.tracker_file import ConflictRecord, TrackerFile, tracker_path
from agent_build_kit.pipeline.work_graph import read_tasks
from tests.cli.e2e_hold_fakes import abk
from tests.cli.tracker_fakes import KIND, SECTION, planned, served
from tests.trackers.apply_support import AppliedBoard
from tests.trackers.board_support import CHANGE

LEVELS = ["change", "group", "task"]
EDITED = "Add the report in `src/app/report.py` and print it. Verify: 2.1 passes."


@pytest.fixture(autouse=True)
def registered_kind() -> Iterator[None]:
    yield
    trackers.unregister("azure_devops")


def test_an_open_conflict_is_commented_on_the_item_once_over_three_polls(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    removed = run.item_id("1")

    run.board.person().update(removed, {"state": "removed"})
    for round_ in range(3):
        run.board.person().update(removed, {"tags": f"seen-{round_}"})
        run.apply()

    assert len(run.open_conflicts()) == 1
    assert len(run.comments_on(removed)) == 1


def test_two_conflicts_on_one_item_are_each_commented_once(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    edited = run.item_id("1")

    run.board.person().update(edited, {"title": "A title a person chose"})
    run.apply()
    run.board.person().update(edited, {"state": "removed"})
    run.apply()
    run.board.person().update(edited, {"tags": "once more"})
    run.apply()

    assert {c.field for c in run.open_conflicts()} == {"title", "removed"}
    assert len(run.comments_on(edited)) == 2


def test_agreement_closes_a_text_conflict_on_the_next_poll(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    task = run.item_id("2.2")
    key = f"{CHANGE}:2.2"
    run.tasks.write_text(
        run.tasks.read_text().replace("Add the report in", "Add the whole report in")
    )
    run.board.person().update(task, {"title": EDITED, "body": EDITED})
    run.apply()
    assert [(c.item_id, c.field) for c in run.open_conflicts()] == [(task, "body")]

    [spec_text] = [t.text for t in read_tasks(run.tasks, CHANGE) if t.key == key]
    run.board.person().update(task, {"title": spec_text, "body": spec_text})
    applied = run.apply()

    assert run.open_conflicts() == []
    assert applied.conflicts == ()


def test_status_lists_each_open_conflict_with_its_item_and_field(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planned(tmp_path, SECTION)
    folder = config.parent / "openspec" / "changes" / "feature"
    folder.mkdir(parents=True)
    recorded = TrackerFile(
        kind=KIND,
        target="example-org",
        conflicts=(
            ConflictRecord(item_id="4411", field="title", spec_value="A", tracker_value="B"),
            ConflictRecord(item_id="4412", field="removed", spec_value="A"),
            ConflictRecord(item_id="4413", field="body", status="closed"),
        ),
    )
    tracker_path(folder).write_text(yaml.safe_dump(recorded.model_dump(mode="json")))

    with served():
        code, out, err = abk(config, capsys, "status")

    assert code == 0, err
    lines = out + err
    assert any("4411" in line and "title" in line for line in lines)
    assert any("4412" in line and "removed" in line for line in lines)
    assert not any("4413" in line for line in lines)


def test_a_conflict_records_who_changed_the_item_and_when(tmp_path: Path) -> None:
    run = AppliedBoard(tmp_path, LEVELS)
    removed = run.item_id("1")

    run.board.person().update(removed, {"state": "removed"})
    run.apply()

    [record] = run.open_conflicts()
    made = [c for c in run.board.changed_since(None)[0] if c.item_id == removed][-1]
    assert (record.who, record.when) == (made.who, made.when)


def test_status_says_when_a_changes_epic_was_closed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config = planned(tmp_path, SECTION)
    folder = config.parent / "openspec" / "changes" / "feature"
    folder.mkdir(parents=True)
    recorded = TrackerFile(kind=KIND, target="example-org", epic="9001", epic_warned=True)
    tracker_path(folder).write_text(yaml.safe_dump(recorded.model_dump(mode="json")))

    with served():
        code, out, err = abk(config, capsys, "status")

    assert code == 0, err
    assert any("feature" in line and "9001" in line for line in out + err)
