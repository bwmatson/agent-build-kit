"""A review card is raised only for units that need a person (spec: review-triage, a card is
raised only for units that need a person's attention)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.notify.cards import desired_cards
from agent_build_kit.notify.provider import CardKind
from agent_build_kit.notify.reconcile import reconcile
from agent_build_kit.notify.store import NotificationStore
from agent_build_kit.pipeline.unit_store import HeldBy
from agent_build_kit.pipeline.units import FAILED, HELD, IN_REVIEW
from agent_build_kit.pipeline.verdict import ReviewTier
from tests import fake_clock
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.fake_clock import FakeClock
from tests.landing_support import apply_review, listed_review
from tests.notify_fakes import FakeNotifier, enabled
from tests.verdict_fakes import write_verdicts

UNIT = "add-marker/1"
REVIEW_CARD = f"unit:review:{UNIT}"


@pytest.fixture(autouse=True)
def policy(tmp_path: Path) -> None:
    """The class `docs` is listed for landing, so an `auto` unit of it will be landed."""
    apply_review(make_installation(tmp_path), listed_review())


@pytest.fixture
def verdicts(tmp_path: Path) -> Path:
    return tmp_path / "verdicts.json"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return fake_clock.install(monkeypatch)


def in_review():
    return stored_unit(UNIT, state=IN_REVIEW, pr=5)


@pytest.mark.parametrize("tier", [ReviewTier.LIGHT, ReviewTier.FULL])
def test_a_light_or_full_unit_in_review_has_a_review_card(verdicts: Path, tier: ReviewTier) -> None:
    write_verdicts(verdicts, {UNIT: tier})

    cards = desired_cards([in_review()], verdicts)

    assert [(card.id, card.kind) for card in cards] == [(REVIEW_CARD, CardKind.REVIEW)]


def test_an_auto_unit_in_review_has_no_card(verdicts: Path) -> None:
    write_verdicts(verdicts, {UNIT: ReviewTier.AUTO}, unit_class="docs")

    assert desired_cards([in_review()], verdicts) == []


def test_a_unit_with_no_verdict_has_a_review_card_as_before(verdicts: Path) -> None:
    write_verdicts(verdicts, {"other/1": ReviewTier.AUTO})

    cards = desired_cards([in_review()], verdicts)

    assert [card.id for card in cards] == [REVIEW_CARD]


@pytest.mark.parametrize("tier", list(ReviewTier))
@pytest.mark.parametrize(
    ("unit", "kind"),
    [
        (stored_unit(UNIT, state=FAILED), CardKind.FAILED),
        (stored_unit(UNIT, state=HELD, held_by=HeldBy.REVIEW), CardKind.HELD),
    ],
    ids=["failed", "held"],
)
def test_a_failed_or_held_unit_has_its_card_whatever_its_tier(
    verdicts: Path, tier: ReviewTier, unit, kind: CardKind
) -> None:
    write_verdicts(verdicts, {UNIT: tier})

    assert [card.kind for card in desired_cards([unit], verdicts)] == [kind]


def test_a_card_for_a_unit_whose_tier_became_auto_is_cleared_by_reconciliation(
    clock: FakeClock, verdicts: Path, tmp_path: Path
) -> None:
    notifier = FakeNotifier()
    path = tmp_path / "notifications.json"

    def round_() -> None:
        reconcile(
            [in_review()],
            store=NotificationStore(path),
            notifier=notifier,
            config=enabled(),
            log=lambda line: None,
            verdicts=verdicts,
        )

    write_verdicts(verdicts, {UNIT: ReviewTier.LIGHT})
    round_()
    assert notifier.shown_ids == [REVIEW_CARD]

    clock.advance(60)
    write_verdicts(verdicts, {UNIT: ReviewTier.AUTO}, unit_class="docs")
    round_()

    assert notifier.cleared == [REVIEW_CARD]
    assert NotificationStore(path).entries() == {}
