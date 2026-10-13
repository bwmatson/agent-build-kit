"""The lane's agent calls are `restack` rows for the unit moved, with its change and repository,
each asked of the guard first; a clean move in the lane writes no row and asks nothing.

Two units are moved by the lane `abk tick` builds, one that conflicts with `main` and one that
applies cleanly, over the usage ledger the pipeline writes.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import PLANNED
from agent_build_kit.pipeline.usage_ledger import UsageRecord, read_ledger
from tests.factories import git, stored_unit
from tests.restack_lane_fakes import asked_of_the_guard, moved_onto_main, restack, tracked_rig
from tests.restack_turn_fakes import OLD_BASE, Rig, commit_file
from tests.usage_host import Host, payload

CLEAN = "spec/c/3"


@pytest.fixture
def rig(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: Host) -> Rig:
    return tracked_rig(tmp_path, monkeypatch, host)


def restack_rows(rig: Rig) -> list[UsageRecord]:
    ledger = rig.installation.state_dir / "usage-ledger.jsonl"
    return [row for row in read_ledger(ledger) if row.node == "restack"]


def test_a_conflicting_restack_in_the_lane_writes_restack_rows_and_a_clean_move_writes_none(
    rig: Rig, host: Host, monkeypatch: pytest.MonkeyPatch
) -> None:
    git(rig.repo, "checkout", "-q", "-b", CLEAN, OLD_BASE)
    commit_file(rig.repo, "extra.py", "EXTRA = 1\n")
    git(rig.repo, "checkout", "-q", "main")
    rig.store.upsert([stored_unit("c/3", change="c", branch=CLEAN)])
    rig.store.set_state("c/3", PLANNED, cause=Cause.BASE_CHANGED, branch=CLEAN)
    host.keep_reading(timedelta(seconds=30), payload(session=10.0))
    decisions = asked_of_the_guard(monkeypatch)

    restack(rig)

    assert moved_onto_main(rig, CLEAN) and moved_onto_main(rig, rig.branch)
    rows = restack_rows(rig)
    assert rows, "the resolver's call was not recorded"
    assert {(row.unit, row.change, row.repo) for row in rows} == {
        (rig.child.id, rig.child.change, rig.child.repo)
    }
    assert len(decisions) == len(rows), "each call of the resolver was asked of the guard first"
