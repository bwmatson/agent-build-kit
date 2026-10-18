"""A scheduled unit builds nothing: it goes from `prepare` to the whole-suite e2e-test step, ends
satisfied when it passes, and its change archives by the existing path (spec: e2e-schedule)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.e2e_schedule import write_due
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.units import SATISFIED
from tests.e2e_schedule_fakes import TODAY
from tests.e2e_scope_fakes import WHOLE, Ran
from tests.factories import git
from tests.runner_fakes import Killed
from tests.scheduled_e2e_fakes import (
    CHANGE,
    SUMMARY,
    ScheduledRun,
    archiving,
    archiving_on,
    scheduled_unit,
)

BUILD_STEPS = {"claude:tests", "claude:impl", "claude:rework", "claude:fix_checks", "review"}
PUBLISHED = {"push", "pr", "status", "close"}


@pytest.mark.parametrize("feedback", ["", "e2e-test failed:\nFAILED tests/live/test_live.py::t"])
def test_a_scheduled_unit_goes_from_prepare_to_e2e_and_builds_nothing(
    tmp_path: Path, feedback: str
) -> None:
    run = ScheduledRun(tmp_path, feedback=feedback)

    outcome = run.tick()

    recorder = run.recorder
    assert outcome.status == RunStatus.SATISFIED
    assert run.ran.commands, "e2e-test ran"
    assert recorder.prompts == [], "no agent was called"
    assert not (BUILD_STEPS | PUBLISHED) & set(recorder.events)
    assert not [event for event in recorder.events if event.startswith(("commit", "unit-test"))]
    assert recorder.pr_calls == 0 and recorder.remote == []


def test_the_whole_marker_runs_whatever_the_scope_setting_says(tmp_path: Path) -> None:
    run = ScheduledRun(tmp_path)

    run.tick()

    assert run.ran.commands == [WHOLE], "own did not narrow it, though the tree adds no test"
    assert any("runs whole" in line for line in run.log)


def test_a_pass_ends_the_unit_satisfied_with_the_counts_and_the_commit_and_ticks_its_tasks(
    tmp_path: Path,
) -> None:
    run = ScheduledRun(tmp_path)

    outcome = run.tick()

    stored = run.stored
    assert outcome.status == RunStatus.SATISFIED
    assert stored.state == SATISFIED
    assert stored.note == "scheduled e2e-test passed for rest: 2 passed, 1 skipped on abc1234"
    assert stored.pr is None and "pr" not in run.recorder.events
    assert stored.feedback == ""
    tasks = (run.inst.changes_dir / CHANGE / "tasks.md").read_text()
    assert "- [x] 1.1" in tasks and "- [ ]" not in tasks


def test_the_run_starts_from_the_default_branch_tip_as_of_the_start(tmp_path: Path) -> None:
    order: list[str] = []

    class Seen(Ran):
        """Keeps the commit each command ran on, read as it ran."""

        heads: list[str] = []

        def __call__(self, command: list[str], **kwargs: object):
            order.append("e2e-test")
            self.heads.append(git(Path(str(kwargs["cwd"])), "rev-parse", "HEAD").strip())
            return super().__call__(command, **kwargs)

    run = ScheduledRun(tmp_path, make_ran=lambda tree: Seen(SUMMARY))
    run.tick(fetch=lambda unit: order.append("fetch"))
    assert run.ran.heads == [run.base]
    tip = run.advance("fixed.txt")

    run.tick(fetch=lambda unit: order.append("fetch"))

    assert order == ["fetch", "e2e-test", "fetch", "e2e-test"], (
        "fetched before each run of the suite"
    )
    assert run.ran.heads == [run.base, tip], "the reused worktree is moved to the new tip"


def test_a_new_runner_resumed_at_satisfied_still_has_the_note_of_the_run(tmp_path: Path) -> None:
    run = ScheduledRun(tmp_path)
    killed = run.tick  # the process dies in `satisfied`, after e2e-test was checkpointed

    def die(unit: object) -> list[str]:
        raise Killed("satisfied")

    with pytest.raises(Killed):
        killed(release_dependents=die)

    def refuse(**kwargs: object) -> None:
        raise AssertionError("e2e-test is not run again")

    outcome = run.tick(
        run_e2e=refuse,
        e2e_passed_note=lambda: "no result in a new runner",
        release_dependents=lambda unit: [],
    )

    assert outcome.status == RunStatus.SATISFIED
    assert run.stored.note == "scheduled e2e-test passed for rest: 2 passed, 1 skipped on abc1234"


def test_a_satisfied_scheduled_units_change_is_archived_by_the_existing_path(
    tmp_path: Path,
) -> None:
    run = ScheduledRun(tmp_path)
    run.tick()

    archived = archive_ready_changes(run.store.all(), planning_repo=run.inst.root, run=archiving)

    assert archived == [CHANGE]
    assert not (run.inst.changes_dir / CHANGE).exists()
    assert (run.inst.changes_dir / "archive" / f"{TODAY.isoformat()}-{CHANGE}").is_dir()


def test_the_next_due_date_is_read_from_the_archived_name(tmp_path: Path) -> None:
    run = ScheduledRun(tmp_path)
    run.tick()
    # Archived later than written: the due date is the name's, not the archive prefix's.
    archive_ready_changes(
        run.store.all(),
        planning_repo=run.inst.root,
        run=archiving_on(TODAY + timedelta(days=3)),
    )
    assert run.stored.id == scheduled_unit().id

    def due(days: int) -> list[str]:
        return write_due(run.inst, run.store, today=TODAY + timedelta(days=days), say=print)

    assert due(6) == []
    assert due(7) == [f"scheduled-e2e-app-{(TODAY + timedelta(days=7)).isoformat()}-rest"]
