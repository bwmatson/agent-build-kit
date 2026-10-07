"""Every hold path of the graph's boundary and rebase nodes records its cause.

The note on the entry is prose for people; the cause is what the pass reads to
decide whether a held unit is let back in. Each path is driven to its hold and
the entry it left is read, so rewording a note breaks nothing here.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_build_kit.forges.base import BaseMissing
from agent_build_kit.pipeline.restack import HostMoved
from agent_build_kit.pipeline.stack_runner import RunOutcome, RunStatus
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import PLANNED
from tests.factories import unit
from tests.graph.test_build_path import build
from tests.graph.test_remaining_paths import CONFLICTED, RESOLVED, Moves
from tests.runner_fakes import Recorder

Held = Callable[[Path, Recorder], RunOutcome]


def fresh(tmp_path: Path) -> Recorder:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([unit()])
    return Recorder(store)


def upstream_went_back(tmp_path: Path, recorder: Recorder) -> RunOutcome:
    return build(
        tmp_path,
        recorder,
        upstream_incomplete=lambda u: (Cause.UPSTREAM_WENT_BACK, "a/0 went back for rework"),
    )


def base_moved_at_a_boundary(tmp_path: Path, recorder: Recorder) -> RunOutcome:
    return build(
        tmp_path,
        recorder,
        base_moved=lambda u, base, **kw: (Cause.BASE_CHANGED, f"its base moved from {base}"),
    )


def base_needing_resolution_twice(tmp_path: Path, recorder: Recorder) -> RunOutcome:
    # The push-time move, the resumed run's own restack, its push-time move.
    moves = Moves(recorder, RESOLVED, None, RESOLVED)
    return build(tmp_path, recorder, **moves.overrides(existing=2))


def base_conflicting_twice(tmp_path: Path, recorder: Recorder) -> RunOutcome:
    moves = Moves(recorder, CONFLICTED, None, CONFLICTED)
    return build(tmp_path, recorder, **moves.overrides(existing=2))


def base_gone_that_the_forge_still_names(tmp_path: Path, recorder: Recorder) -> RunOutcome:
    def gone(u: Any, *, body: str, base: str, cwd: Path, **bodies: str) -> int:
        raise BaseMissing("base branch spec/add-marker/0 does not exist")

    return build(
        tmp_path,
        recorder,
        base="spec/add-marker/0",
        branch_commits=lambda cwd, base: 2 + recorder.made,
        fresh_base=lambda u, base: "spec/add-marker/0",
        open_pr=gone,
    )


def push_the_host_moved(tmp_path: Path, recorder: Recorder) -> RunOutcome:
    recorder.push_raises = HostMoved("the host moved it")
    return build(tmp_path, recorder)


# Each path and the cause it must record; every one leaves the unit `planned`.
HOLD_PATHS: list[tuple[Held, Cause]] = [
    (upstream_went_back, Cause.UPSTREAM_WENT_BACK),
    (base_moved_at_a_boundary, Cause.BASE_CHANGED),
    (base_needing_resolution_twice, Cause.BASE_CHANGED),
    (base_conflicting_twice, Cause.BASE_CHANGED),
    (base_gone_that_the_forge_still_names, Cause.BASE_CHANGED),
    (push_the_host_moved, Cause.RESTACK_DEFERRED),
]


@pytest.mark.parametrize(("hold", "cause"), HOLD_PATHS, ids=[h.__name__ for h, _ in HOLD_PATHS])
def test_each_hold_path_records_the_cause_it_found(
    tmp_path: Path, hold: Held, cause: Cause
) -> None:
    recorder = fresh(tmp_path)

    outcome = hold(tmp_path, recorder)

    entry = recorder.store.get(unit().id).history[-1]
    assert outcome.status == RunStatus.HELD
    assert entry["state"] == PLANNED
    assert entry.get("note"), "there is still prose for a person"
    assert entry.get("cause") == cause
