"""Archiving a change once its work has landed.

Archiving folds a change's spec deltas into `openspec/specs/`, which is what
keeps those specs describing current behaviour rather than aspirations
(docs/architecture.md). It is also the one step that edits the
planning repo's own history, so it has to be careful:

- **Only when every unit has merged.** Archiving early would publish
  behaviour that isn't in `main` yet.
- **In merge order.** Two changes touching the same requirement conflict at
  archive time, and the later one must apply on top of the earlier.
- **Never twice.** The graph is re-planned every round, so "all merged" stays
  true forever after.
"""

import logging
import subprocess
from pathlib import Path

import pytest

from agent_build_kit.pipeline.archive import (
    archive_ready_changes,
    is_ready_to_archive,
)
from agent_build_kit.pipeline.unit_store import StoredUnit
from tests.factories import stored_unit


def unit(uid: str, change: str = "add-marker", **overrides) -> StoredUnit:
    """Merged unless a test says otherwise: archiving is about finished work."""
    return stored_unit(uid, change=change, **{"state": "merged", **overrides})


def test_a_change_with_every_unit_merged_is_ready() -> None:
    assert is_ready_to_archive("add-marker", [unit("add-marker/1"), unit("add-marker/2")])


def test_one_unmerged_unit_holds_the_whole_change_back() -> None:
    """Archiving now would publish behaviour that isn't in main."""
    units = [unit("add-marker/1"), unit("add-marker/2", state="in_review")]

    assert not is_ready_to_archive("add-marker", units)


def test_a_change_with_no_units_is_not_ready() -> None:
    """Nothing merged is not the same as everything merged, and an empty
    change would otherwise archive itself the moment it appeared."""
    assert not is_ready_to_archive("add-marker", [])


def test_a_dropped_unit_does_not_block_forever() -> None:
    """A unit the plan no longer contains is marked unplanned; waiting for it
    to merge would strand the change permanently."""
    units = [unit("add-marker/1"), unit("add-marker/2", state="unplanned")]

    assert is_ready_to_archive("add-marker", units)


def test_a_satisfied_unit_does_not_block_archiving() -> None:
    """A satisfied unit added nothing of its own, so it never opens a PR and
    never merges; waiting for one to merge would strand the change forever,
    the same as waiting for a dropped unit would."""
    units = [unit("add-marker/1"), unit("add-marker/2", state="satisfied")]

    assert is_ready_to_archive("add-marker", units)


def test_a_satisfied_unit_on_an_unmerged_branch_is_not_ready() -> None:
    """It stacked on another change's branch, still in review: archiving now
    would publish behaviour that is not in main."""
    units = [
        unit("add-marker/1", change="add-marker", state="in_review"),
        unit("feature/1", change="feature", state="satisfied", depends_on=("add-marker/1",)),
    ]

    assert not is_ready_to_archive("feature", units)


def test_a_satisfied_unit_is_ready_once_what_it_stacked_on_has_merged() -> None:
    units = [
        unit("add-marker/1", change="add-marker", state="merged"),
        unit("feature/1", change="feature", state="satisfied", depends_on=("add-marker/1",)),
    ]

    assert is_ready_to_archive("feature", units)


def test_a_satisfied_unit_with_no_same_repo_dependency_is_ready() -> None:
    assert is_ready_to_archive("feature", [unit("feature/1", change="feature", state="satisfied")])


def test_a_closed_unit_blocks_archiving() -> None:
    """Closed means someone rejected that work, so the change is not done —
    it needs a human, not an archive."""
    units = [unit("add-marker/1"), unit("add-marker/2", state="closed")]

    assert not is_ready_to_archive("add-marker", units)


class FakeRunner:
    """Stands in for subprocess.run: records the OpenSpec CLI invocation."""

    def __init__(self, *, fails: bool = False) -> None:
        self.calls: list[list[str]] = []
        self.fails = fails

    def __call__(self, args: list[str], *, cwd: Path, **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(list(args))
        if self.fails:
            return subprocess.CompletedProcess(args, 1, "", "archive conflicted")
        return subprocess.CompletedProcess(args, 0, "archived\n", "")


class FailingFor(FakeRunner):
    """Fails the archive of one named change, as the CLI does on a conflict."""

    def __init__(self, change: str) -> None:
        super().__init__()
        self.change = change

    def __call__(self, args: list[str], *, cwd: Path, **kwargs) -> subprocess.CompletedProcess:
        result = super().__call__(args, cwd=cwd, **kwargs)
        if self.change in args:
            return subprocess.CompletedProcess(args, 1, "", "archive conflicted\nmore detail")
        return result


def make_change(planning_repo: Path, change: str) -> None:
    directory = planning_repo / "openspec" / "changes" / change
    directory.mkdir(parents=True)
    (directory / "tasks.md").write_text("# Tasks\n")


def test_a_ready_change_is_archived(tmp_path: Path) -> None:
    make_change(tmp_path, "add-marker")
    runner = FakeRunner()

    archived = archive_ready_changes([unit("add-marker/1")], planning_repo=tmp_path, run=runner)

    assert archived == ["add-marker"]
    assert any("archive" in " ".join(call) for call in runner.calls)


def test_archiving_is_not_interactive(tmp_path: Path) -> None:
    """There is nobody to answer a prompt in an unattended run."""
    make_change(tmp_path, "add-marker")
    runner = FakeRunner()

    archive_ready_changes([unit("add-marker/1")], planning_repo=tmp_path, run=runner)

    assert any("--yes" in call for call in runner.calls)


def test_changes_are_archived_in_merge_order(tmp_path: Path) -> None:
    """Two changes touching the same requirement conflict at archive time, and
    the later one has to apply on top of the earlier."""
    make_change(tmp_path, "first")
    make_change(tmp_path, "second")
    runner = FakeRunner()
    units = [
        unit("second/1", change="second", history=({"state": "merged", "at": "2026-09-23T12:00"},)),
        unit("first/1", change="first", history=({"state": "merged", "at": "2026-09-23T09:00"},)),
    ]

    archived = archive_ready_changes(units, planning_repo=tmp_path, run=runner)

    assert archived == ["first", "second"]


def test_an_already_archived_change_is_not_archived_again(tmp_path: Path) -> None:
    """ "All merged" stays true forever, so without this every round would try
    again and fail noisily."""
    runner = FakeRunner()
    (tmp_path / "openspec" / "changes" / "archive" / "2026-09-23-add-marker").mkdir(parents=True)

    archived = archive_ready_changes([unit("add-marker/1")], planning_repo=tmp_path, run=runner)

    assert archived == []
    assert runner.calls == []


def test_a_failed_archive_does_not_stop_the_others(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Archiving is housekeeping: one change's conflict must not end the tick
    before the others are archived or anything is built."""
    runner = FailingFor("first")
    units = [
        unit("first/1", change="first", history=({"state": "merged", "at": "2026-09-23T09:00"},)),
        unit("second/1", change="second", history=({"state": "merged", "at": "2026-09-23T12:00"},)),
    ]
    make_change(tmp_path, "first")
    make_change(tmp_path, "second")

    with caplog.at_level(logging.WARNING):
        archived = archive_ready_changes(units, planning_repo=tmp_path, run=runner)

    assert archived == ["second"]
    assert len(runner.calls) == 2
    assert "first" in caplog.text
    assert "archive conflicted" in caplog.text


def test_a_failed_archive_is_retried_and_logged_again_on_the_next_call(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Nothing remembers a failure: each tick tries again and says so again."""
    runner = FailingFor("first")
    units = [
        unit("first/1", change="first", history=({"state": "merged", "at": "2026-09-23T09:00"},)),
        unit("second/1", change="second", history=({"state": "merged", "at": "2026-09-23T12:00"},)),
    ]
    make_change(tmp_path, "first")
    make_change(tmp_path, "second")

    with caplog.at_level(logging.WARNING):
        archive_ready_changes(units, planning_repo=tmp_path, run=runner)
        archive_ready_changes(units, planning_repo=tmp_path, run=runner)

    assert sum("first" in call and "archive" in call for call in runner.calls) == 2
    failures = [
        r
        for r in caplog.records
        if "first" in r.getMessage() and "archive conflicted" in r.getMessage()
    ]
    assert len(failures) == 2


def test_a_change_with_no_directory_is_logged_as_withdrawn_and_not_attempted(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    runner = FakeRunner()

    with caplog.at_level(logging.WARNING):
        archived = archive_ready_changes(
            [unit("add-marker/1")],
            planning_repo=tmp_path,
            run=runner,
        )

    assert archived == []
    assert runner.calls == []
    assert "add-marker" in caplog.text
    assert "withdrawn" in caplog.text


def test_a_change_not_yet_verified_live_is_held_back(tmp_path: Path) -> None:
    """Archive waits for the live check (verify.py): a change whose deploy or
    live tests failed stays open, not folded into the specs as done."""
    runner = FakeRunner()

    archived = archive_ready_changes(
        [unit("add-marker/1")], planning_repo=tmp_path, run=runner, may_archive=lambda change: False
    )

    assert archived == []
    assert runner.calls == []
