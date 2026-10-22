"""A pull request carries a label for its unit's review tier (spec: review-triage).

Cosmetic like the state labels: the forge is a stand-in that records which labels each
pull request carries, and no failure of a label write is a unit's problem.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_build_kit.pipeline.labels import StateLabels
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW, MERGED
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.verdict_record import VerdictEntry
from agent_build_kit.pipeline.vocabulary import review_label, review_label_names, state_label_names
from tests.factories import activate_with, stored_unit
from tests.forges.stand_in import NoLabelsForge, StandInForge, lookup

PR = 7
UNIT = "add-marker/1"


@pytest.fixture(autouse=True)
def review_enabled() -> None:
    activate_with(review={"enabled": True})


@pytest.fixture
def forge() -> StandInForge:
    return StandInForge()


@pytest.fixture
def logged() -> list[str]:
    return []


@pytest.fixture
def labels(forge: StandInForge, logged: list[str]) -> StateLabels:
    return StateLabels(lookup(forge), log=logged.append)


@pytest.fixture
def verdicts(tmp_path: Path) -> Path:
    return tmp_path / "verdicts.json"


def record(path: Path, tier: ReviewTier) -> None:
    entry = VerdictEntry(
        unit=UNIT,
        change="add-marker",
        round=1,
        final=True,
        unit_class="app/unit-test",
        planned_estimate=None,
        classification=tier,
        drivers=(),
        evidence_tier=tier,
        tier=tier,
        reason="because",
        paths=(),
        lines=3,
        brief=True,
    )
    path.write_text(json.dumps({UNIT: entry.model_dump(mode="json", exclude={"split"})}))


def in_review() -> StoredUnit:
    return stored_unit(UNIT, state=IN_REVIEW, pr=PR)


def review_on_pr(forge: StandInForge) -> set[str]:
    return forge.on_pr.get(PR, set()) & review_label_names()


def test_a_unit_with_a_light_verdict_gets_the_light_label_alone(
    forge: StandInForge, labels: StateLabels, verdicts: Path
) -> None:
    record(verdicts, ReviewTier.LIGHT)

    labels.follow_review(in_review(), verdicts)

    assert review_on_pr(forge) == {review_label(ReviewTier.LIGHT).name}


def test_a_later_full_verdict_replaces_the_label(
    forge: StandInForge, labels: StateLabels, verdicts: Path
) -> None:
    record(verdicts, ReviewTier.LIGHT)
    labels.follow_review(in_review(), verdicts)

    record(verdicts, ReviewTier.FULL)
    labels.follow_review(in_review(), verdicts)

    assert review_on_pr(forge) == {review_label(ReviewTier.FULL).name}


def test_a_person_s_own_label_survives_the_swap(
    forge: StandInForge, labels: StateLabels, verdicts: Path
) -> None:
    forge.on_pr[PR] = {"bug"}
    record(verdicts, ReviewTier.AUTO)

    labels.follow_review(in_review(), verdicts)

    assert forge.on_pr[PR] == {"bug", review_label(ReviewTier.AUTO).name}


def test_a_unit_with_no_verdict_gets_no_review_label(
    forge: StandInForge, labels: StateLabels, verdicts: Path
) -> None:
    labels.follow_review(in_review(), verdicts)

    assert review_on_pr(forge) == set()
    assert not forge.label_creations
    assert review_label_names(), "the family exists, so an empty result is not an empty family"


def test_a_unit_with_no_pull_request_gets_no_review_label(
    forge: StandInForge, labels: StateLabels, verdicts: Path
) -> None:
    record(verdicts, ReviewTier.FULL)

    labels.follow_review(stored_unit(UNIT, state=IN_REVIEW, pr=None), verdicts)

    assert not forge.on_pr
    assert not forge.label_creations
    assert review_label_names()


def test_with_review_disabled_no_label_is_written(
    forge: StandInForge, labels: StateLabels, verdicts: Path
) -> None:
    activate_with(review={"enabled": False})
    record(verdicts, ReviewTier.FULL)

    labels.follow_review(in_review(), verdicts)

    assert not forge.on_pr
    assert not forge.label_creations
    assert review_label_names()


def test_a_host_that_keeps_no_labels_is_said_so_once_and_raises_nothing(
    logged: list[str], verdicts: Path
) -> None:
    labels = StateLabels(lookup(NoLabelsForge()), log=logged.append)
    record(verdicts, ReviewTier.LIGHT)

    labels.follow_review(in_review(), verdicts)
    labels.follow_review(in_review(), verdicts)

    assert len(logged) == 1, logged


def test_a_failing_label_call_is_logged_and_not_raised(logged: list[str], verdicts: Path) -> None:
    labels = StateLabels(lookup(StandInForge(label_errors=("set",))), log=logged.append)
    record(verdicts, ReviewTier.LIGHT)

    labels.follow_review(in_review(), verdicts)

    assert len(logged) == 1, logged


def test_clearing_a_merged_unit_s_state_labels_leaves_the_review_label(
    forge: StandInForge, labels: StateLabels
) -> None:
    labels.set_state("app", PR, "in_review")
    labels.set_review("app", PR, ReviewTier.FULL)

    labels.follow(stored_unit(UNIT, state=MERGED, pr=PR), [], opened=False)

    assert forge.on_pr[PR] == {review_label(ReviewTier.FULL).name}
    assert not forge.on_pr[PR] & state_label_names()


def test_setting_a_review_label_leaves_the_state_label(
    forge: StandInForge, labels: StateLabels
) -> None:
    labels.set_state("app", PR, "in_review")

    labels.set_review("app", PR, ReviewTier.LIGHT)

    assert forge.on_pr[PR] == {"in-review", review_label(ReviewTier.LIGHT).name}
