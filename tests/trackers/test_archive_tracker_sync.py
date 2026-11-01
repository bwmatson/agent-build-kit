"""A tracker write after the archive commit never makes planning sync stop (spec: tracker-push).

Over real git (a bare origin and the pipeline worktree): a mirrored change is archived through
`abk verify`, with the archive published as a branch, the tracker step then finishes its board, the
archive branch lands, and the planning sync moves the worktree to the new tip."""

from __future__ import annotations

import argparse
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_build_kit import forges, openspec, trackers
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline.planning_sync import SyncOutcome, sync_planning
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import UnitState
from agent_build_kit.pipeline.verify import Verification
from agent_build_kit.trackers.tick_step import sync_trackers
from tests.factories import git, stored_unit
from tests.forges.stand_in import StandInForge
from tests.planning_worktree_support import InRepo, in_repo, installation_at
from tests.progress_support import write_copy
from tests.trackers.board_support import CHANGE, DESIGN, PROPOSAL, SPEC, TASKS, TYPES
from tests.trackers.reconciler_support import RecordingTracker
from tests.trackers.tracker_section_support import AZURE_BLOCK, configure

UNIT = f"{CHANGE}/1"
SPECS = f"openspec/changes/{CHANGE}"
FILES = {
    f"{SPECS}/proposal.md": PROPOSAL,
    f"{SPECS}/design.md": DESIGN,
    f"{SPECS}/specs/lanes/spec.md": SPEC,
    f"{SPECS}/tasks.md": TASKS,
    "abk.yaml": "repos: {}\n",
}


class GitHubHost(StandInForge):
    name = "github"


@pytest.fixture(autouse=True)
def board(monkeypatch: pytest.MonkeyPatch) -> Iterator[RecordingTracker]:
    tracker = RecordingTracker()
    trackers.register("azure_devops", lambda section: tracker)

    def archive(change: str, *, cwd: Path, run=None) -> str:
        changes = cwd / "openspec" / "changes"
        (changes / "archive").mkdir(exist_ok=True)
        shutil.move(changes / change, changes / "archive" / f"2026-01-01-{change}")
        return "archived"

    monkeypatch.setattr(openspec, "archive", archive)
    forges.register(GitHubHost(number=41))
    yield tracker
    trackers.unregister("azure_devops")


def mirrored(tmp_path: Path, publish: str) -> tuple[InRepo, Installation, UnitStore]:
    setup = in_repo(tmp_path, files=FILES)
    inst = installation_at(
        setup.worktree,
        setup.working_copy,
        planning=dict(publish=publish, state_dir=str(tmp_path / "state")),
    )
    configure(
        app={
            "kind": "azure_devops",
            "levels": ["change", "group"],
            "azure_devops": {**AZURE_BLOCK, "types": TYPES},
        }
    )
    store = UnitStore(inst.state_dir / "units.json")
    store.upsert([stored_unit(UNIT, change=CHANGE, repo="app", groups=(1, 2))])
    store.set_state(UNIT, UnitState.IN_REVIEW, pr=5, branch=f"spec/{UNIT}")
    sync_trackers(inst, store.all())
    store.set_state(UNIT, UnitState.MERGED, pr=5, branch=f"spec/{UNIT}")
    write_copy(inst, CHANGE, TASKS.replace("[ ]", "[x]"))
    return setup, inst, store


def archive(inst: Installation, monkeypatch: pytest.MonkeyPatch) -> None:
    def passed(inst: Installation, change: str, units: list) -> Verification:
        return Verification(change=change, passed=True)

    monkeypatch.setattr(cli, "verify_one", passed)
    assert cli.cmd_verify(argparse.Namespace(change=CHANGE), inst) == 0


def state_of(tracker: RecordingTracker, marker: str) -> str:
    item = tracker.find_by_marker(marker)
    assert item is not None, marker
    return item.kit_state or item.state


@pytest.mark.parametrize("publish", ["branch", "direct"])
def test_a_board_finished_after_the_archive_does_not_stop_the_planning_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, board: RecordingTracker, publish: str
) -> None:
    setup, inst, store = mirrored(tmp_path, publish)
    assert state_of(board, CHANGE) == "active"
    archive(inst, monkeypatch)

    sync_trackers(inst, store.all())

    assert state_of(board, CHANGE) == "done"
    assert state_of(board, f"{CHANGE}:1") == "done"
    if publish == "direct":
        assert "tracker.yaml" not in git(setup.worktree, "status", "--porcelain")
    if publish == "branch":
        origin = setup.origin
        assert origin is not None
        [head] = [
            line.split()[-1] for line in git(origin, "branch", "--list", "planning/*").splitlines()
        ]
        git(origin, "update-ref", "refs/heads/main", f"refs/heads/{head}")

    synced = sync_planning(inst, lambda message: None)

    assert synced.outcome != SyncOutcome.STOPPED, synced.reason
    assert state_of(board, CHANGE) == "done"
