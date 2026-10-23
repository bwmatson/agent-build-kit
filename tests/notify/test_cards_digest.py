"""One digest card lists what auto-landed in the last 24 hours (spec: auto-land, a digest card
lists what auto-landed)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.notify.cards import desired_cards
from agent_build_kit.notify.provider import CardKind
from agent_build_kit.pipeline.verdict import ReviewTier
from tests import fake_clock
from tests.conftest import make_installation
from tests.fake_clock import FakeClock
from tests.notify_fakes import landed_unit
from tests.verdict_fakes import write_verdicts


@pytest.fixture
def clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    make_installation(tmp_path)
    return fake_clock.install(monkeypatch)


@pytest.fixture
def verdicts(tmp_path: Path) -> Path:
    path = tmp_path / "verdicts.json"
    write_verdicts(path, dict.fromkeys(("c/1", "c/2"), ReviewTier.AUTO), unit_class="docs")
    return path


def link(pr: int) -> str:
    forge, repo = forges.for_repo("app")
    return forge.web_url(repo, pr=pr)


def test_two_landings_this_morning_give_one_card_listing_both(
    clock: FakeClock, verdicts: Path
) -> None:
    now = clock.now()
    units = [
        landed_unit("c/1", now - timedelta(hours=2), pr=7),
        landed_unit("c/2", now - timedelta(hours=1), pr=8),
    ]

    (card,) = desired_cards(units, verdicts)

    assert card.kind is CardKind.DIGEST
    assert not card.remind
    for unit_id, pr in (("c/1", 7), ("c/2", 8)):
        assert unit_id in card.body
        assert link(pr) in card.body
    assert card.body.count("docs") >= 2, "each unit's class is listed"


def test_a_landing_a_day_and_an_hour_old_is_not_listed(clock: FakeClock, verdicts: Path) -> None:
    now = clock.now()
    units = [
        landed_unit("c/1", now - timedelta(hours=25), pr=7),
        landed_unit("c/2", now - timedelta(hours=1), pr=8),
    ]

    (card,) = desired_cards(units, verdicts)

    assert "c/2" in card.body
    assert "c/1" not in card.body


def test_no_landing_in_the_window_gives_no_card(clock: FakeClock, verdicts: Path) -> None:
    recent = landed_unit("c/1", clock.now() - timedelta(hours=23))
    assert len(desired_cards([recent], verdicts)) == 1

    clock.advance(2 * 3600)

    assert desired_cards([recent], verdicts) == []
    assert desired_cards([], verdicts) == []


def test_the_card_s_id_changes_with_the_date_of_the_newest_landing(
    clock: FakeClock, verdicts: Path
) -> None:
    first = landed_unit("c/1", clock.now() - timedelta(hours=1), pr=7)
    (before,) = desired_cards([first], verdicts)

    clock.advance(20 * 3600)  # the next morning, the first landing still inside the window
    second = landed_unit("c/2", clock.now() - timedelta(hours=1), pr=8)
    (after,) = desired_cards([first, second], verdicts)

    assert before.id != after.id
    assert before.kind is after.kind is CardKind.DIGEST
    assert str(clock.now().date()) in after.id


def test_a_landed_unit_raises_no_card_of_its_own(clock: FakeClock, verdicts: Path) -> None:
    cards = desired_cards([landed_unit("c/1", clock.now() - timedelta(hours=1))], verdicts)

    assert [card.kind for card in cards] == [CardKind.DIGEST]
