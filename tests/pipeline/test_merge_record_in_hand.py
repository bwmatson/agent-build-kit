"""A seen merge is recorded with the commit the pull-request snapshot carries, and the forge is
asked only when nothing in hand has it (spec: github-merge-commit).

The dispatch is the poller's own, with the merge record the pipeline gives it; the forge is the
stand-in, which counts what it was asked."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.base import PullRequest
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.unit_store import UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED, SETTLING
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.forges.stand_in import StandInForge

UNIT = "add-marker/1"
PR = 1
LISTED = "c" * 40
ASKED = "f" * 40


class World:
    def __init__(self, tmp_path: Path, patch: pytest.MonkeyPatch) -> None:
        self.inst: Installation = make_installation(tmp_path)
        self.inst.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = UnitStore(self.inst.state_dir / "units.json")
        self.store.upsert([stored_unit(UNIT)])
        self.store.set_state(UNIT, IN_REVIEW, pr=PR, branch=f"spec/{UNIT}")
        self.forge = StandInForge()
        self.forge.merged[PR] = ASKED
        forge = self.forge
        patch.setattr(self.inst, "forge_of", lambda repo: (forge, forge.repo_id()))
        self.dispatch: Callable[..., bool] = events.build_dispatch(
            self.store,
            restack=lambda **k: None,
            remove_worktree=lambda repo, branch: None,
            delete_branch=lambda repo, branch: None,
            retarget=lambda unit, base: None,
            merge_record=lambda unit: cli.merge_record_of(self.inst, unit),
            log=lambda message: None,
        )


def snapshot(commit: str | None) -> PullRequest:
    return PullRequest(
        number=PR, head=f"spec/{UNIT}", base="main", state="merged", merge_commit=commit
    )


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    return World(tmp_path, monkeypatch)


def test_a_merge_seen_in_the_listing_is_recorded_with_its_commit_and_no_forge_read(
    world: World,
) -> None:
    world.dispatch("merged", PR, repo="app", pull=snapshot(LISTED))

    unit = world.store.get(UNIT)
    assert unit.state == SETTLING
    assert unit.merge_sha == LISTED
    assert [pull.merge_sha for pull in unit.pulls] == [LISTED]
    assert world.forge.merge_commit_reads == [], "the forge was not asked for the merge commit"


def test_a_merge_seen_with_no_commit_in_hand_asks_the_forge_once(world: World) -> None:
    world.dispatch("merged", PR, repo="app", pull=snapshot(None))

    assert world.store.get(UNIT).merge_sha == ASKED
    assert world.forge.merge_commit_reads == [PR]


def test_a_settling_unit_with_no_commit_takes_the_snapshot_s_when_it_settles(
    world: World,
) -> None:
    world.store.set_state(UNIT, SETTLING)

    world.dispatch("settled", PR, repo="app", pull=snapshot(LISTED))

    unit = world.store.get(UNIT)
    assert (unit.state, unit.merge_sha) == (MERGED, LISTED)
    assert world.forge.merge_commit_reads == []


def test_the_merge_record_of_a_unit_with_a_stored_commit_does_not_ask_the_forge(
    world: World,
) -> None:
    world.store.set_merge_record(UNIT, LISTED, None)

    sha, _ = cli.merge_record_of(world.inst, world.store.get(UNIT))

    assert sha == LISTED
    assert world.forge.merge_commit_reads == []
