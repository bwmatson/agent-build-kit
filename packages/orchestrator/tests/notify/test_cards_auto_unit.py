"""An `auto` unit in review raises a review card unless the landing step will land it (spec:
auto-land, an auto unit that will not land is not hidden)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.notify.cards import desired_cards
from agent_build_kit.pipeline import demotion_record
from agent_build_kit.pipeline.landing_decision import Condition
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.verdict import ReviewTier
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.forges.stand_in import StandInForge
from tests.landing_support import apply_review, listed_review
from tests.verdict_fakes import write_verdicts

UNIT = "c/1"
REVIEW_CARD = f"unit:review:{UNIT}"


@pytest.fixture
def verdicts(tmp_path: Path) -> Path:
    apply_review(make_installation(tmp_path), listed_review(listed=("docs",)))
    return tmp_path / "verdicts.json"


def in_review(*, declined: Condition | None = None) -> StoredUnit:
    """The unit in review; `declined` is the condition the landing step last declined it for."""
    history = ()
    if declined is not None:
        history = (
            {
                "state": IN_REVIEW,
                "at": "2030-01-01T09:00:00+00:00",
                "event": "landing_declined",
                "note": f"not landed — {declined.value}",
                "condition": declined.value,
            },
        )
    return stored_unit(UNIT, state=IN_REVIEW, pr=5, history=history)


def card_ids(unit: StoredUnit, verdicts: Path, **kwargs) -> list[str]:
    return [card.id for card in desired_cards([unit], verdicts, **kwargs)]


def test_an_auto_unit_of_a_class_not_listed_has_a_review_card(verdicts: Path) -> None:
    write_verdicts(verdicts, {UNIT: ReviewTier.AUTO}, unit_class="other")

    assert card_ids(in_review(), verdicts) == [REVIEW_CARD]


def test_an_auto_unit_of_a_demoted_class_has_a_review_card(verdicts: Path) -> None:
    write_verdicts(verdicts, {UNIT: ReviewTier.AUTO}, unit_class="docs")

    assert card_ids(in_review(), verdicts, demoted_classes=("docs",)) == [REVIEW_CARD]


def test_an_auto_unit_whose_forge_does_not_merge_has_a_review_card(
    verdicts: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    forge = StandInForge()
    forge.merges = False
    monkeypatch.setattr(forges, "for_repo", lambda name: (forge, forge.repo_id()))
    write_verdicts(verdicts, {UNIT: ReviewTier.AUTO}, unit_class="docs")

    assert card_ids(in_review(), verdicts) == [REVIEW_CARD]


def test_an_auto_unit_declined_for_having_no_checks_has_a_review_card(verdicts: Path) -> None:
    write_verdicts(verdicts, {UNIT: ReviewTier.AUTO}, unit_class="docs")

    assert card_ids(in_review(declined=Condition.NO_CHECKS), verdicts) == [REVIEW_CARD]


def test_an_auto_unit_of_a_listed_class_waiting_for_pending_checks_has_none(
    verdicts: Path,
) -> None:
    write_verdicts(verdicts, {UNIT: ReviewTier.AUTO}, unit_class="docs")

    waiting = in_review(declined=Condition.CHECKS_PENDING)

    assert card_ids(waiting, verdicts) == []
    assert card_ids(in_review(), verdicts) == []
    assert card_ids(waiting, verdicts, demoted_classes=("docs",)) == [REVIEW_CARD], (
        "waiting for checks hides a unit only while the landing step will land it"
    )


def test_an_auto_unit_of_a_class_demoted_in_the_file_has_a_review_card_before_any_decline(
    verdicts: Path, tmp_path: Path
) -> None:
    write_verdicts(verdicts, {UNIT: ReviewTier.AUTO}, unit_class="docs")
    demotions = tmp_path / demotion_record.DEMOTIONS
    demotion_record.demote(
        demotions,
        unit_class="docs",
        trigger="revert",
        unit="c/9",
        at=datetime(2026, 1, 1, tzinfo=UTC),
        say=lambda _: None,
    )

    assert REVIEW_CARD in card_ids(in_review(), verdicts, demotions=demotions)


def test_an_unreadable_demotion_file_does_not_hide_the_review_card(
    verdicts: Path, tmp_path: Path
) -> None:
    write_verdicts(verdicts, {UNIT: ReviewTier.AUTO}, unit_class="docs")
    demotions = tmp_path / demotion_record.DEMOTIONS
    demotions.write_text("not json")

    assert REVIEW_CARD in card_ids(in_review(), verdicts, demotions=demotions)
