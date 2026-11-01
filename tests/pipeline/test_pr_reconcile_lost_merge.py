"""The step that lost a merge: a pull request merged while its unit was being built.

A requeued unit keeps the pull request it first opened. A person merges it while the
unit runs, and the build then finishes and calls `open_pr`. The run holds the unit's
branch lock for its whole length, so the handlers (which take that lock to deliver an
event to the unit's thread) cannot record the merge from inside it. The run must end
without putting the unit in review, and the merge is recorded by the first dispatch made
after the lock is released, before any new build starts.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.events import build_claim, build_dispatch
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING, SETTLING, Unit
from tests.graph_driver import fresh, tick

MERGE_COMMIT = "9f2c1ab"
UNIT = "add-marker/1"
PR = 7


def test_a_pull_request_merged_during_the_build_is_recorded_once_the_run_has_released_its_lock(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    store = recorder.store
    store.set_state(UNIT, RUNNING, pr=PR, branch=f"spec/{UNIT}")
    # The poller's dispatch as the tick builds it: it claims the unit's branch.
    dispatch = build_dispatch(
        store,
        restack=lambda **kwargs: None,
        claim=build_claim(tmp_path / "locks"),
        merge_record=lambda unit: (MERGE_COMMIT, 7),
        log=recorder.log,
    )
    inside: list[bool] = []

    def forge_state(unit: Unit, pr: int) -> str:
        # The merge came after the build began, and is asked about while the run holds the
        # lock: the handler cannot take the branch then, so it defers.
        if not recorder.events:
            return "open"
        inside.append(dispatch("merged", pr, repo=unit.repo))
        return "merged"

    outcome = tick(tmp_path, recorder, forge_state=forge_state)

    assert inside == [False], "a dispatch made inside the run is deferred by the lock"
    assert outcome.pr_over == "merged"
    assert store.get(UNIT).state == RUNNING, "nothing was recorded inside the run"
    assert store.get(UNIT).state != IN_REVIEW
    assert not any("in review" in line for line in recorder.logged), recorder.logged
    built = list(recorder.events)

    assert dispatch(outcome.pr_over, PR, repo="app") is True, "the lock is released"

    unit = store.get(UNIT)
    assert unit.state == SETTLING
    assert unit.merge_sha == MERGE_COMMIT
    assert recorder.events == built, "no new build started in between"
