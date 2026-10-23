"""A unit awaiting audit has an audit card, cleared once the result is recorded, and `abk status`
lists the audits waiting (spec: auto-land, a sampled share of landed units is audited)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit import forges
from agent_build_kit.notify.cards import Card, desired_cards
from agent_build_kit.notify.provider import CardKind
from agent_build_kit.pipeline import audit_record
from agent_build_kit.pipeline.unit_store import StoredUnit, UnitStore
from tests import fake_clock
from tests.conftest import make_installation, status_lines
from tests.fake_clock import FakeClock
from tests.notify_fakes import landed_unit

AT = datetime(2026, 1, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    make_installation(tmp_path)
    return fake_clock.install(monkeypatch)


@pytest.fixture
def audits(tmp_path: Path) -> Path:
    return tmp_path / audit_record.AUDITS


def link(pr: int) -> str:
    forge, repo = forges.for_repo("app")
    return forge.web_url(repo, pr=pr)


def audit_cards(units: Sequence[StoredUnit], audits: Path) -> list[Card]:
    return [c for c in desired_cards(units, audits=audits) if c.kind is CardKind.AUDIT]


def test_a_unit_awaiting_audit_has_an_audit_card_with_a_link_to_its_pull_request(
    clock: FakeClock, audits: Path
) -> None:
    unit = landed_unit("c/1", clock.now() - timedelta(hours=1), pr=7)
    audit_record.record_awaiting(audits, unit="c/1", unit_class="docs", at=AT)

    (card,) = audit_cards([unit], audits)

    assert "c/1" in card.title + card.body
    assert card.link == link(7)


def test_each_unit_awaiting_audit_has_its_own_card(clock: FakeClock, audits: Path) -> None:
    units = [
        landed_unit("c/1", clock.now() - timedelta(hours=1), pr=7),
        landed_unit("c/2", clock.now() - timedelta(hours=2), pr=8),
    ]
    for unit in units:
        audit_record.record_awaiting(audits, unit=unit.id, unit_class="docs", at=AT)

    cards = audit_cards(units, audits)

    assert len(cards) == 2
    assert len({card.id for card in cards}) == 2


def test_the_card_is_cleared_once_the_result_is_recorded(clock: FakeClock, audits: Path) -> None:
    unit = landed_unit("c/1", clock.now() - timedelta(hours=1), pr=7)
    audit_record.record_awaiting(audits, unit="c/1", unit_class="docs", at=AT)
    assert len(audit_cards([unit], audits)) == 1

    audit_record.record_result(audits, unit="c/1", result="ok", at=AT + timedelta(hours=1))

    assert audit_cards([unit], audits) == []


def test_status_lists_each_audit_waiting_with_its_unit_and_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def record(store: UnitStore) -> None:
        path = tmp_path / audit_record.AUDITS
        audit_record.record_awaiting(path, unit="c/1", unit_class="docs", at=AT)
        audit_record.record_awaiting(path, unit="c/2", unit_class="code", at=AT)
        audit_record.record_awaiting(path, unit="c/3", unit_class="docs", at=AT)
        audit_record.record_result(path, unit="c/3", result="ok", at=AT)

    unit = landed_unit("c/1", AT)
    lines = status_lines(tmp_path, monkeypatch, capsys, [unit], record=record)

    waiting = [line for line in lines if "audit" in line]
    assert len(waiting) == 2
    assert "c/1" in waiting[0] and "docs" in waiting[0]
    assert "c/2" in waiting[1] and "code" in waiting[1]
    assert not any("c/3" in line for line in waiting)
