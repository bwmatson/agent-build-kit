"""The step that lost a merge: a pull request merged while its unit was being built.

A requeued unit keeps the pull request it first opened. A person merges it while the
unit runs, the poller's report is deferred because the unit is being built, and the
build then finishes and calls `open_pr`. The unit must end recorded merged, and never
sit in review on a pull request that has already merged.
"""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.events import build_dispatch
from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING, SETTLING
from tests.graph_driver import fresh, tick

MERGE_COMMIT = "9f2c1ab"
UNIT = "add-marker/1"


def test_a_pull_request_merged_during_the_build_is_recorded_when_the_build_finishes(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)
    store = recorder.store
    store.set_state(UNIT, RUNNING, pr=7, branch=f"spec/{UNIT}")

    tick(
        tmp_path,
        recorder,
        # The merge came after the build began: the forge has it merged by the time the
        # build asks.
        forge_state=lambda unit, pr: "merged" if recorder.events else "open",
        dispatch=build_dispatch(
            store,
            restack=lambda **kwargs: None,
            merge_record=lambda unit: (MERGE_COMMIT, 7),
            log=recorder.log,
        ),
    )

    unit = store.get(UNIT)
    assert unit.state == SETTLING, f"left {unit.state} on a merged PR: {recorder.logged}"
    assert unit.state != IN_REVIEW
    assert unit.merge_sha == MERGE_COMMIT
    assert not any("in review" in line for line in recorder.logged), recorder.logged
