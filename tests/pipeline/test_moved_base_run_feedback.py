"""A unit with feedback of its own is a build; one whose feedback review has approved over
is owed a moved-base run, and the answered feedback is cleared as the run starts
(spec: unit-scheduling)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.pipeline.restack_lane import (
    clear_answered_feedback,
    moved_base_units,
    owed_a_moved_base_run,
    owed_units,
)
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, StoredUnit, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import git, stored_unit
from tests.restack_lane_fakes import caused, repo_behind

HEAD = "head-1"
UNIT = "feature/2"

REWORK_INPUT = [
    FeedbackSource.REVIEW,
    FeedbackSource.CI,
    FeedbackSource.UNIT_TEST,
    FeedbackSource.E2E,
    FeedbackSource.NONE,
]


def subject(**changes: Any) -> StoredUnit:
    fields: dict[str, Any] = {
        "cause": Cause.BASE_CHANGED,
        "branch": "spec/feature/2",
        "feedback": "please fix the naming",
        **changes,
    }
    return caused(UNIT, PLANNED, fields.pop("cause"), **fields)


def owed(unit: StoredUnit) -> bool:
    return owed_a_moved_base_run(
        unit,
        [unit],
        has_commits=lambda unit: True,
        head=lambda unit: HEAD,
        held=lambda unit: False,
        leased=lambda unit: False,
    )


@pytest.mark.parametrize("source", REWORK_INPUT)
def test_feedback_no_approval_covers_makes_the_unit_a_build(source: FeedbackSource) -> None:
    assert owed(subject(feedback_source=source, approved=HEAD))

    assert not owed(subject(feedback_source=source, approved="older-head"))
    assert not owed(subject(feedback_source=source))


def test_feedback_that_names_the_conflict_is_not_rework_input() -> None:
    conflicted = subject(
        cause=Cause.REWORK, feedback_source=FeedbackSource.CONFLICT, approved="older-head"
    )

    assert owed(conflicted)


def feedback_store(tmp_path: Path, source: FeedbackSource) -> UnitStore:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([stored_unit(UNIT, change="feature")])
    store.set_feedback(UNIT, "please fix the naming", source=source)
    return store


@pytest.mark.parametrize("source", REWORK_INPUT)
def test_answered_feedback_is_cleared_as_the_run_starts(
    source: FeedbackSource, tmp_path: Path
) -> None:
    store = feedback_store(tmp_path, source)

    clear_answered_feedback(store, store.get(UNIT).model_copy(update={"approved": HEAD}), HEAD)

    assert store.get(UNIT).feedback == ""
    assert store.get(UNIT).feedback_source is FeedbackSource.NONE


def test_feedback_no_approval_covers_is_kept_as_the_run_starts(tmp_path: Path) -> None:
    store = feedback_store(tmp_path, FeedbackSource.REVIEW)

    clear_answered_feedback(store, store.get(UNIT).model_copy(update={"approved": "older"}), HEAD)

    assert store.get(UNIT).feedback == "please fix the naming"


def test_a_unit_with_unanswered_feedback_is_still_moved_by_the_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst = repo_behind(tmp_path, monkeypatch)
    repo = inst.checkouts["app"]
    git(repo, "checkout", "-q", "spec/feature/3")
    (repo / "c.txt").write_text("c\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "c")
    git(repo, "checkout", "-q", "main")
    unit = caused(
        "feature/3",
        PLANNED,
        Cause.BASE_CHANGED,
        branch="spec/feature/3",
        feedback="please fix the naming",
        feedback_source=FeedbackSource.REVIEW,
    )

    assert owed_units(inst, [unit]) == {"feature/3"}
    assert moved_base_units(inst, [unit]) == set()
