"""The digest card is shown once, never reminded, and cleared when the window empties; a
review card still reminds (spec: auto-land, a digest card lists what auto-landed)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.notify.reconcile import reconcile
from agent_build_kit.pipeline.unit_store import StoredUnit
from agent_build_kit.pipeline.units import IN_REVIEW
from agent_build_kit.pipeline.verdict import ReviewTier
from tests import fake_clock
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.fake_clock import FakeClock
from tests.notify_fakes import Rounds, enabled, landed_unit
from tests.verdict_fakes import write_verdicts

REMIND_MINUTES = 60
REVIEW_CARD = "unit:review:c/2"


@pytest.fixture
def clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    make_installation(tmp_path)
    return fake_clock.install(monkeypatch)


@pytest.fixture
def rounds(clock: FakeClock, tmp_path: Path) -> Rounds:
    config = enabled(remind_after_minutes=REMIND_MINUTES)
    return Rounds(tmp_path / "notifications.json", clock, config)


@pytest.fixture
def verdicts(tmp_path: Path) -> Path:
    path = tmp_path / "verdicts.json"
    write_verdicts(path, {"c/1": ReviewTier.AUTO, "c/2": ReviewTier.LIGHT}, unit_class="docs")
    return path


def tick(rounds: Rounds, units: list[StoredUnit], verdicts: Path, *, minutes: float = 0) -> None:
    rounds.clock.advance(minutes * 60)
    reconcile(
        units,
        store=rounds.store(),
        notifier=rounds.notifier,
        config=rounds.config,
        log=rounds.lines.append,
        verdicts=verdicts,
    )


def digests(rounds: Rounds) -> list[str]:
    return [id for id in rounds.notifier.shown_ids if id.startswith("digest")]


def test_a_digest_card_is_shown_once(rounds: Rounds, verdicts: Path) -> None:
    landed = landed_unit("c/1", rounds.clock.now())

    tick(rounds, [landed], verdicts)

    assert len(digests(rounds)) == 1


def test_it_is_not_shown_again_when_the_reminder_interval_passes(
    rounds: Rounds, verdicts: Path
) -> None:
    landed = landed_unit("c/1", rounds.clock.now())
    tick(rounds, [landed], verdicts)

    tick(rounds, [landed], verdicts, minutes=REMIND_MINUTES + 1)
    tick(rounds, [landed], verdicts, minutes=REMIND_MINUTES + 1)

    assert len(digests(rounds)) == 1
    assert rounds.notifier.cleared == []


def test_it_is_cleared_when_the_window_empties(rounds: Rounds, verdicts: Path) -> None:
    landed = landed_unit("c/1", rounds.clock.now())
    tick(rounds, [landed], verdicts)
    (digest,) = digests(rounds)

    tick(rounds, [landed], verdicts, minutes=25 * 60)

    assert rounds.notifier.cleared == [digest]
    assert rounds.store().entries() == {}


def test_a_review_card_still_reminds_beside_the_digest(rounds: Rounds, verdicts: Path) -> None:
    units = [landed_unit("c/1", rounds.clock.now()), stored_unit("c/2", state=IN_REVIEW, pr=5)]
    tick(rounds, units, verdicts)

    tick(rounds, units, verdicts, minutes=REMIND_MINUTES + 1)

    assert rounds.notifier.shown_ids.count(REVIEW_CARD) == 2
    assert len(digests(rounds)) == 1
