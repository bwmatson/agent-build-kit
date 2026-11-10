"""The pipeline lands a unit the landing decision allows and records it (spec: auto-land).

The forge is a stand-in that records what it was asked to merge; the merge is recorded through
the poller's own dispatch, over fake restack and cleanup, as a person's merge is.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.forges.base import PullRequest
from agent_build_kit.pipeline import landing as landing_step
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


def test_its_children_are_recorded_as_owed_a_move_as_for_a_person_s_merge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)

    landed.land()

    assert landed.store.get("c/2").cause is Cause.BASE_CHANGED, "\n".join(landed.logged)
    assert landed.restacked == [], "nothing is moved in the pass"


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


# --- the merge commit, from the merge's own answer --------------------------------

SQUASHED = "d" * 40


def test_a_landing_seeds_the_audit_sample_on_the_merge_s_commit_without_asking_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seeded: list[tuple[str, str]] = []

    def picked(unit: str, commit: str, rate: float) -> bool:
        seeded.append((unit, commit))
        return False

    monkeypatch.setattr(landing_step, "picked", picked)
    landed = landing(tmp_path, monkeypatch, StandInForge(merge_sha=SQUASHED))

    landed.land()

    assert seeded == [(UNIT, SQUASHED)], "\n".join(landed.logged)
    assert landed.forge.merge_commit_reads == [], "the forge was not asked for the merge commit"


def test_a_landing_records_the_merge_s_commit_on_the_unit_without_asking_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch, StandInForge(merge_sha=SQUASHED))

    landed.land()

    unit = landed.store.get(UNIT)
    assert unit.merge_sha == SQUASHED, "\n".join(landed.logged)
    assert [pull.merge_sha for pull in unit.pulls] == [SQUASHED]
    assert landed.forge.merge_commit_reads == []


def test_a_merge_that_failed_asks_the_forge_for_the_commit_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forge = StandInForge(
        merge_failures=[RuntimeError("the connection dropped")], merge_lands_before_failing=True
    )
    landed = landing(tmp_path, monkeypatch, forge)

    landed.land()

    assert forge.merge_commit_reads == [PR]


def test_a_merge_the_listing_shows_with_its_commit_is_recorded_without_asking_for_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    landed = landing(tmp_path, monkeypatch)
    landed.forge.prs[:] = [
        PullRequest(
            number=PR, head=f"spec/{UNIT}", base="main", state="merged", merge_commit=SQUASHED
        )
    ]

    landed.land()

    unit = landed.store.get(UNIT)
    assert unit.merge_sha == SQUASHED, "\n".join(landed.logged)
    assert landed.forge.merge_commit_reads == []
