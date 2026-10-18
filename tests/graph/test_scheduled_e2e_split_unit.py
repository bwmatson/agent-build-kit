"""The unit of a scheduled split's change runs the whole marker restricted to that split, ends
satisfied with a note naming the split, and waits, change open, while the split is held
(spec: e2e-split-runs)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.pipeline.archive import archive_ready_changes
from agent_build_kit.pipeline.e2e import build_selection
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED, SATISFIED
from agent_build_kit.profiles.python_uv import PROFILE
from tests.e2e_park_fakes import GATE_CLEARED
from tests.e2e_scope_fakes import KIT_SPLITS
from tests.scheduled_e2e_fakes import ScheduledRun, archiving

MARKER = "local_stack"
REASON = "the provider is down"
SPLITS = ("rest", "acp", "claude_code")


def expected(split: str) -> str:
    """The `-m` text of a run of the whole marker restricted to `split`."""
    return PROFILE.expression(MARKER, build_selection(MARKER, KIT_SPLITS, only=split))


def expressions(run: ScheduledRun) -> list[str]:
    return [command[command.index("-m") + 1] for command in run.ran.commands]


@pytest.mark.parametrize("split", SPLITS)
def test_the_unit_runs_the_selection_of_its_split_alone(tmp_path: Path, split: str) -> None:
    run = ScheduledRun(tmp_path, split=split, declared=True)

    outcome = run.tick()

    assert outcome.status == RunStatus.SATISFIED
    assert expressions(run) == [expected(split)]


@pytest.mark.parametrize("split", SPLITS)
def test_a_pass_ends_the_unit_satisfied_with_a_note_naming_the_split_and_the_counts(
    tmp_path: Path, split: str
) -> None:
    run = ScheduledRun(tmp_path, split=split, declared=True)

    run.tick()

    assert run.stored.state == SATISFIED
    assert run.stored.note.startswith("scheduled e2e-test passed")
    assert split in run.stored.note
    assert "2 passed, 1 skipped" in run.stored.note
    for other in set(SPLITS) - {split}:
        assert other not in run.stored.note


def test_the_unit_of_a_held_split_runs_nothing_and_waits_with_its_change_open(
    tmp_path: Path,
) -> None:
    run = ScheduledRun(tmp_path, split="acp", held={"acp": REASON})

    outcome = run.tick()

    assert outcome.status == RunStatus.HELD
    assert run.ran.commands == []
    assert (run.stored.state, run.stored.cause) == (PLANNED, Cause.SPLIT_HELD)
    assert "acp" in run.stored.note and REASON in run.stored.note
    assert run.stored.parked_splits == ["acp"]
    archived = archive_ready_changes(run.store.all(), planning_repo=run.inst.root, run=archiving)
    assert archived == []
    assert (run.inst.changes_dir / run.subject.change).is_dir()


def test_the_units_of_the_other_splits_run_while_a_split_is_held(tmp_path: Path) -> None:
    held = {"acp": REASON}
    runs = {
        split: ScheduledRun(tmp_path / split, split=split, declared=True, held=held)
        for split in SPLITS
    }

    outcomes = {split: run.tick().status for split, run in runs.items()}

    assert outcomes == {
        "rest": RunStatus.SATISFIED,
        "acp": RunStatus.HELD,
        "claude_code": RunStatus.SATISFIED,
    }
    assert expressions(runs["rest"]) == [expected("rest")]
    assert expressions(runs["claude_code"]) == [expected("claude_code")]
    assert runs["acp"].ran.commands == []


def test_the_unit_resumes_and_runs_its_split_when_the_split_is_released(tmp_path: Path) -> None:
    run = ScheduledRun(tmp_path, split="acp", held={"acp": REASON})
    assert run.tick().status == RunStatus.HELD

    run.held.clear()
    run.tick(event=GATE_CLEARED)
    outcome = run.tick()

    assert outcome.status == RunStatus.SATISFIED
    assert expressions(run) == [expected("acp")]
    assert run.stored.state == SATISFIED
    assert run.stored.parked_splits == []
    assert "acp" in run.stored.note
