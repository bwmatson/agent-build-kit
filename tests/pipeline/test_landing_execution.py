"""The pipeline lands a unit the landing decision allows and records it (spec: auto-land).

The forge is a stand-in that records what it was asked to merge; the merge is recorded through
the poller's own dispatch, over fake restack and cleanup, as a person's merge is.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.forges.base import PullRequest
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import events
from agent_build_kit.pipeline.landing_intent import LANDING, has_intent
from agent_build_kit.pipeline.pr_poller import HOLD_LABEL
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED
from tests.conftest import make_installation
from tests.factories import deep_store
from tests.forges.stand_in import StandInForge
from tests.landing_support import HEAD, apply_review, listed_review, make_landable

UNIT = "c/1"
PR = 1


class Landing:
    """A store of units in review, a forge, and the landing pass over them."""

    def __init__(self, tmp_path: Path, patch: pytest.MonkeyPatch, forge: StandInForge) -> None:
        self.inst: Installation = make_installation(tmp_path)
        apply_review(self.inst, listed_review())
        self.inst.state_dir.mkdir(parents=True, exist_ok=True)
        self.store: UnitStore = deep_store(self.inst.state_dir)
        self.forge = forge
        self.restacked: list[tuple[str, str, str]] = []
        self.logged: list[str] = []
        patch.setattr(self.inst, "forge_of", lambda repo: (forge, forge.repo_id()))
        make_landable(self.inst, self.store, forge, {UNIT: PR})
        self.dispatch: Callable[..., bool] = events.build_dispatch(
            self.store,
            restack=lambda **k: self.restacked.append((k["branch"], k["old_base"], k["new_base"])),
            remove_worktree=lambda repo, branch: None,
            delete_branch=lambda repo, branch: None,
            retarget=lambda unit, base: None,
            rebase_cap=2,
            landing_path=self.inst.state_dir / LANDING,
            log=lambda message: None,
        )

    def land(self) -> None:
        cli.land_units(self.inst, self.store, dispatch=self.dispatch, say=self.logged.append)

    def intent(self, pr: int = PR) -> bool:
        return has_intent(self.inst.state_dir / LANDING, repo="app", pr=pr)


def landing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, forge: StandInForge | None = None
) -> Landing:
    return Landing(tmp_path, monkeypatch, forge or StandInForge())


def test_a_unit_that_may_land_is_merged_once_at_its_approved_head(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)

    landed.land()

    assert landed.forge.merge_calls == [(PR, HEAD)]


def test_it_is_recorded_merged_with_the_cause_auto_landed_and_its_intent_removed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)

    landed.land()

    unit = landed.store.get(UNIT)
    assert (unit.state, unit.cause) == (MERGED, Cause.AUTO_LANDED), "\n".join(landed.logged)
    assert not landed.intent()


def test_its_children_are_restacked_as_for_a_person_s_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)

    landed.land()

    assert ("spec/c/2", "spec/c/1", "main") in landed.restacked, "\n".join(landed.logged)


def test_a_unit_that_may_not_land_is_not_merged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)
    landed.forge.on_pr[PR] = {HOLD_LABEL}

    landed.land()

    assert landed.forge.merge_calls == []
    assert landed.store.get(UNIT).state == IN_REVIEW
    assert landed.logged, "the pass says what it did"


def test_a_refusal_leaves_the_unit_in_review_with_the_reason_and_no_intent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch, StandInForge(merge_refusal="the head moved"))

    landed.land()

    unit = landed.store.get(UNIT)
    assert unit.state == IN_REVIEW
    assert "the head moved" in unit.note, "the reason is where `abk status` reads it"
    assert not landed.intent()
    assert landed.forge.merge_calls == [(PR, HEAD)]


def test_a_second_pass_over_the_landed_unit_merges_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)
    landed.land()
    history = landed.store.get(UNIT).history

    landed.land()

    assert landed.forge.merge_calls == [(PR, HEAD)]
    assert landed.store.get(UNIT).history == history


def test_a_pull_request_a_person_already_merged_is_recorded_and_not_merged_again(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)
    landed.forge.prs[:] = [PullRequest(number=PR, head=f"spec/{UNIT}", base="main", state="merged")]

    landed.land()

    unit = landed.store.get(UNIT)
    assert landed.forge.merge_calls == []
    assert (unit.state, unit.cause) == (MERGED, Cause.MERGED), "\n".join(landed.logged)
