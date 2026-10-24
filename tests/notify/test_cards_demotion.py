"""A standing demotion has a card until it is lifted, a lift shows a notice once, and `abk status`
lists the demoted classes (spec: class-demotion, every demotion and lift is notified)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.notify.cards import Card, desired_cards
from agent_build_kit.notify.provider import CardKind
from agent_build_kit.pipeline import demotion_record
from agent_build_kit.pipeline.unit_store import UnitStore
from tests import fake_clock
from tests.conftest import make_installation, status_lines
from tests.fake_clock import FakeClock

AT = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    make_installation(tmp_path)
    return fake_clock.install(monkeypatch)


@pytest.fixture
def demotions(tmp_path: Path) -> Path:
    return tmp_path / demotion_record.DEMOTIONS


def demote(path: Path, unit_class: str = "docs", unit: str = "c/1", at: datetime = AT) -> None:
    demotion_record.demote(
        path, unit_class=unit_class, trigger="revert", unit=unit, at=at, say=lambda _: None
    )


def demotion_cards(demotions: Path) -> list[Card]:
    return [c for c in desired_cards([], demotions=demotions) if c.kind is CardKind.DEMOTION]


def test_a_standing_demotion_has_a_card_naming_the_class_and_the_trigger(
    clock: FakeClock, demotions: Path
) -> None:
    demote(demotions)

    (card,) = demotion_cards(demotions)

    text = card.title + card.body
    assert "docs" in text and "revert" in text and "c/1" in text
    assert card.remind is True


def test_the_card_stays_however_long_the_demotion_stands(clock: FakeClock, demotions: Path) -> None:
    demote(demotions)
    clock.advance(timedelta(days=30).total_seconds())

    assert len(demotion_cards(demotions)) == 1


def test_each_demoted_class_has_its_own_card(clock: FakeClock, demotions: Path) -> None:
    demote(demotions, "docs")
    demote(demotions, "code")

    cards = demotion_cards(demotions)

    assert len(cards) == 2
    assert len({card.id for card in cards}) == 2


def test_a_lift_clears_the_card_and_shows_a_notice_that_is_not_sounded_again(
    clock: FakeClock, demotions: Path
) -> None:
    demote(demotions)
    (standing,) = demotion_cards(demotions)
    demotion_record.lift(demotions, unit_class="docs", at=clock.now())

    (notice,) = demotion_cards(demotions)

    assert notice.id != standing.id
    assert "docs" in notice.title + notice.body
    assert notice.remind is False


def test_the_notice_goes_after_24_hours(clock: FakeClock, demotions: Path) -> None:
    demote(demotions)
    demotion_record.lift(demotions, unit_class="docs", at=clock.now())
    clock.advance(timedelta(hours=23).total_seconds())
    assert len(demotion_cards(demotions)) == 1

    clock.advance(timedelta(hours=2).total_seconds())

    assert demotion_cards(demotions) == []


def test_a_new_demotion_after_a_lift_has_a_standing_card_again(
    clock: FakeClock, demotions: Path
) -> None:
    demote(demotions)
    demotion_record.lift(demotions, unit_class="docs", at=clock.now())
    demote(demotions, unit="c/2", at=clock.now())

    cards = demotion_cards(demotions)

    assert [c.remind for c in cards] == [True]


def test_status_lists_each_demoted_class_with_its_trigger_the_unit_and_since_when(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def record(store: UnitStore) -> None:
        path = tmp_path / demotion_record.DEMOTIONS
        demote(path, "docs", "c/1", AT)
        demote(path, "code", "c/2", AT + timedelta(days=1))
        demote(path, "config", "c/3", AT)
        demotion_record.lift(path, unit_class="config", at=AT)

    lines = status_lines(tmp_path, monkeypatch, capsys, record=record)

    demoted = [line for line in lines if "demoted" in line]
    assert len(demoted) == 2
    docs = next(line for line in demoted if "docs" in line)
    assert "revert" in docs and "c/1" in docs and AT.date().isoformat() in docs
    code = next(line for line in demoted if "code" in line)
    assert "c/2" in code and (AT + timedelta(days=1)).date().isoformat() in code
    assert not any("config" in line for line in demoted)
