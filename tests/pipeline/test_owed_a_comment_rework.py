"""When a unit is owed a comment rework, and the lane's scan for them (spec: resolution-lane).

A unit in review or planned whose cause is `rework`, with feedback, whose branch holds its base
and that no lease or branch lock holds, is owed a run in the resolution lane. The scan reads the
repositories' branches, so these run over a real one.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.lease import Leases, lease_dir
from agent_build_kit.pipeline.resolution_lane import lane_runs_owed, owed_units
from agent_build_kit.pipeline.unit_store import Cause, FeedbackSource, StoredUnit
from agent_build_kit.pipeline.units import HELD, IN_REVIEW, MERGED, PLANNED, RUNNING
from agent_build_kit.pipeline.workspaces import branch_lock
from tests.factories import git
from tests.restack_lane_fakes import caused, repo_behind

UNIT = "feature/4"
BRANCH = "spec/feature/4"
OWED = {UNIT}


def comment_rework(state: str = IN_REVIEW, **changes: Any) -> StoredUnit:
    fields: dict[str, Any] = {
        "branch": BRANCH,
        "feedback": "[comment c1] rename the marker",
        "feedback_source": FeedbackSource.REVIEW,
        **changes,
    }
    return caused(UNIT, state, fields.pop("cause", Cause.REWORK), **fields)


@pytest.fixture
def inst(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Installation:
    """`spec/feature/4` holds `main`, with a commit of its own."""
    inst = repo_behind(tmp_path, monkeypatch)
    repo = inst.checkouts["app"]
    git(repo, "checkout", "-q", "-b", BRANCH, "main")
    (repo / "c.txt").write_text("c\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "c")
    git(repo, "checkout", "-q", "main")
    return inst


def test_a_unit_in_review_or_planned_with_comment_feedback_is_owed_a_run(
    inst: Installation,
) -> None:
    assert owed_units(inst, [comment_rework(IN_REVIEW)]) == OWED
    assert owed_units(inst, [comment_rework(PLANNED)]) == OWED
    assert lane_runs_owed(inst, [comment_rework()]) == OWED


def test_a_running_unit_is_not_owed_a_run(inst: Installation) -> None:
    assert owed_units(inst, [comment_rework()]) == OWED

    assert owed_units(inst, [comment_rework(RUNNING)]) == set()


@pytest.mark.parametrize("state", [HELD, MERGED])
def test_a_held_or_merged_unit_is_not_owed_a_run(inst: Installation, state: str) -> None:
    assert owed_units(inst, [comment_rework()]) == OWED

    assert owed_units(inst, [comment_rework(state)]) == set()


def test_a_unit_with_no_feedback_is_not_owed_a_run(inst: Installation) -> None:
    assert owed_units(inst, [comment_rework()]) == OWED

    assert owed_units(inst, [comment_rework(feedback="")]) == set()


def test_a_unit_a_lease_holds_is_not_owed_a_run(inst: Installation) -> None:
    assert owed_units(inst, [comment_rework()]) == OWED

    assert Leases(lease_dir(inst.local_dir)).take(UNIT, "worker")

    assert owed_units(inst, [comment_rework()]) == set()


def test_a_unit_a_run_holds_the_branch_of_is_not_owed_a_run(inst: Installation) -> None:
    assert owed_units(inst, [comment_rework()]) == OWED

    with branch_lock(BRANCH, root=inst.locks_dir):
        assert owed_units(inst, [comment_rework()]) == set()


def test_a_unit_stopped_for_another_cause_is_not_owed_a_comment_run(inst: Installation) -> None:
    assert owed_units(inst, [comment_rework()]) == OWED

    assert owed_units(inst, [comment_rework(cause=Cause.USAGE)]) == set()


def test_a_unit_waiting_on_an_unmerged_unit_is_not_owed_a_run(inst: Installation) -> None:
    parent = caused("feature/1", PLANNED, None)

    assert owed_units(inst, [comment_rework(), parent]) == OWED

    assert owed_units(inst, [comment_rework(depends_on=("feature/1",)), parent]) == set()
