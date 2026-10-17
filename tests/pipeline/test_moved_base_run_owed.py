"""When a unit is owed a moved-base run, and the lane's scan of the repositories for them
(spec: unit-scheduling).

The graph is built through `waiting_on` only: a unit waits on a same-repo unit that is not yet
in review, never through a gate or a `merged` qualifier.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.restack_lane import moved_base_units, owed_a_moved_base_run
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, StoredUnit
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    SATISFIED,
)
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.factories import git, stored_unit
from tests.restack_lane_fakes import caused, repo_behind

UNIT = "feature/2"


def subject(**changes: Any) -> StoredUnit:
    fields: dict[str, Any] = {
        "state": PLANNED,
        "cause": Cause.BASE_CHANGED,
        "branch": "spec/feature/2",
        **changes,
    }
    return caused(UNIT, fields.pop("state"), fields.pop("cause"), **fields)


def owed(
    unit: StoredUnit,
    *others: StoredUnit,
    commits: bool = True,
    held: bool = False,
    leased: bool = False,
) -> bool:
    return owed_a_moved_base_run(
        unit,
        [unit, *others],
        has_commits=lambda unit: commits,
        head=lambda unit: "head-1",
        held=lambda unit: held,
        leased=lambda unit: leased,
    )


@pytest.mark.parametrize(
    "cause",
    [
        Cause.BASE_CHANGED,
        Cause.RESTACK_DEFERRED,
        Cause.RESTACK_CONFLICT,
        Cause.RESTACK_HANDED_BACK,
    ],
)
def test_a_unit_with_commits_stopped_for_a_moved_base_is_owed_a_run(cause: Cause) -> None:
    assert owed(subject(cause=cause))


def test_a_unit_sent_back_for_a_conflict_is_owed_a_run() -> None:
    conflicted = subject(
        cause=Cause.REWORK, feedback="conflicts", feedback_source=FeedbackSource.CONFLICT
    )

    assert owed(conflicted)


def test_a_unit_a_run_held_for_a_second_moved_base_is_owed_a_run() -> None:
    assert owed(subject(state=PLANNED, cause=Cause.BASE_CHANGED))


def test_a_unit_with_no_commits_is_not_owed_a_run() -> None:
    assert owed(subject())

    assert not owed(subject(), commits=False)


@pytest.mark.parametrize("state", [HELD, FAILED, MERGED, CLOSED, SATISFIED])
def test_a_unit_that_is_held_failed_merged_closed_or_satisfied_is_not_owed(state: str) -> None:
    assert owed(subject())

    assert not owed(subject(state=state))


@pytest.mark.parametrize(
    "case",
    [dict(leased=True), dict(held=True)],
    ids=["a lease", "a held branch lock"],
)
def test_a_unit_that_a_lease_or_a_run_holds_is_not_owed(case: dict[str, bool]) -> None:
    assert owed(subject())

    assert not owed(subject(), **case)


def test_a_unit_waiting_on_another_unit_is_not_owed_until_it_stops() -> None:
    waiting = stored_unit("feature/1", change="feature", state=PLANNED)

    assert not owed(subject(depends_on=("feature/1",)), waiting)

    reviewed = waiting.model_copy(update={"state": IN_REVIEW})
    assert owed(subject(depends_on=("feature/1",)), reviewed)


def test_a_unit_held_for_spent_attempts_is_not_owed() -> None:
    spent = subject(
        state=HELD,
        cause=Cause.RESTACK_CONFLICT,
        conflict_attempts=3,
        conflict_head="head-1",
        pushed="head-1",
    )

    assert not owed(spent)


@pytest.mark.parametrize(
    "cause", [Cause.USAGE, Cause.NEEDS_HUMAN, Cause.RELEASED, Cause.REQUEUED, None]
)
def test_a_unit_stopped_for_another_cause_is_not_owed(cause: Cause | None) -> None:
    assert owed(subject())

    assert not owed(subject(cause=cause))


def test_the_scan_lists_the_units_owed_a_run_and_no_others(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = repo_behind(tmp_path, monkeypatch)
    repo = inst.checkouts["app"]
    git(repo, "checkout", "-q", "spec/feature/3")
    (repo / "c.txt").write_text("c\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "c")
    git(repo, "checkout", "-q", "main")
    git(repo, "branch", "spec/feature/4", "main")
    git(repo, "branch", "spec/feature/5", "spec/feature/3")
    units = [
        caused("feature/3", PLANNED, Cause.BASE_CHANGED, branch="spec/feature/3"),
        caused("feature/4", PLANNED, Cause.BASE_CHANGED, branch="spec/feature/4"),
        caused("feature/5", PLANNED, Cause.RESTACK_HANDED_BACK, branch="spec/feature/5"),
        caused("feature/6", PLANNED, Cause.USAGE, branch="spec/feature/3"),
    ]

    assert moved_base_units(inst, units) == {"feature/3", "feature/5"}

    with branch_lock("spec/feature/3", root=inst.state_dir / "locks"):
        assert moved_base_units(inst, units) == {"feature/5"}
