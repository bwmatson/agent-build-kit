"""The pipeline lands a unit the landing decision allows and records it (spec: auto-land).

The forge is a stand-in that records what it was asked to merge; the merge is recorded through
the poller's own dispatch, over fake restack and cleanup, as a person's merge is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges.base import PullRequest
from agent_build_kit.pipeline.pr_poller import HOLD_LABEL
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import IN_REVIEW, SETTLING
from agent_build_kit.serve.review import ReviewStore
from tests.forges.stand_in import StandInForge
from tests.landing_support import HEAD, PR, UNIT, landing, make_landable


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
    assert (unit.state, unit.cause) == (SETTLING, Cause.AUTO_LANDED), "\n".join(landed.logged)
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
    assert (unit.state, unit.cause) == (SETTLING, Cause.MERGED), "\n".join(landed.logged)


def test_a_child_whose_parent_landed_in_the_same_pass_waits_for_the_next_tick(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)
    make_landable(landed.inst, landed.store, landed.forge, {UNIT: PR, "c/2": 2})

    landed.land()

    assert landed.forge.merge_calls == [(PR, HEAD)]
    assert landed.store.get(UNIT).state == SETTLING
    assert landed.store.get("c/2").state == IN_REVIEW


def test_a_request_for_changes_made_in_the_web_ui_declines_the_unit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)
    reviews = landed.inst.state_dir / "reviews"
    reviews.mkdir()
    ReviewStore(reviews).decide(UNIT, round=1, decision="request_changes", summary="rework it")

    landed.land()

    assert landed.forge.merge_calls == []
    assert landed.store.get(UNIT).state == IN_REVIEW
    assert "changes are requested" in landed.store.get(UNIT).note


def test_an_error_after_the_host_merged_keeps_the_intent_and_is_logged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forge = StandInForge(
        merge_failures=[RuntimeError("the connection dropped")], merge_lands_before_failing=True
    )
    landed = landing(tmp_path, monkeypatch, forge)

    landed.land()

    assert landed.intent(), "the poller records the merge as the pipeline's own"
    assert any("the connection dropped" in line for line in landed.logged)
    assert landed.store.get(UNIT).state == IN_REVIEW
