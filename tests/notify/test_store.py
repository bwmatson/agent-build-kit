"""`notifications.json`: what survives a restart, what is retried, and what two writers share."""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from agent_build_kit.pipeline.units import FAILED, PLANNED
from tests import fake_clock
from tests.factories import stored_unit
from tests.fake_clock import FakeClock
from tests.notify_fakes import FakeNotifier, Rounds, enabled

CARD = "unit:failed:add-marker/1"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return fake_clock.install(monkeypatch)


@pytest.fixture
def rounds(clock: FakeClock, tmp_path: Path) -> Rounds:
    return Rounds(tmp_path / "notifications.json", clock, enabled())


def failed():
    return stored_unit(state=FAILED)


def test_a_restart_neither_repeats_a_shown_card_nor_loses_it(rounds: Rounds) -> None:
    rounds.tick([failed()])
    assert set(rounds.store().entries()) == {CARD}

    # `tick` reads the file afresh each time, as a new process would.
    rounds.tick([failed()], minutes=1)
    assert rounds.notifier.shown_ids == [CARD]

    rounds.tick([stored_unit(state=PLANNED)], minutes=1)
    assert rounds.notifier.cleared == [CARD]


def test_a_shown_card_records_when_it_was_sounded(rounds: Rounds, clock: FakeClock) -> None:
    rounds.tick([failed()])

    entry = rounds.store().entries()[CARD]

    assert entry.sounded_at == clock.now()
    assert entry.pending_since == clock.now()


def test_a_card_waiting_out_its_delay_is_remembered_across_a_restart(
    clock: FakeClock, tmp_path: Path
) -> None:
    rounds = Rounds(tmp_path / "notifications.json", clock, enabled(delay_minutes=10))
    rounds.tick([failed()])

    entry = rounds.store().entries()[CARD]
    assert entry.sounded_at is None
    assert entry.pending_since == clock.now()

    rounds.tick([failed()], minutes=10)
    assert rounds.notifier.shown_ids == [CARD]


def test_a_failed_show_is_not_recorded_and_is_retried(rounds: Rounds) -> None:
    rounds.notifier.fail_show = True
    rounds.tick([failed()])
    assert rounds.store().entries()[CARD].sounded_at is None

    rounds.notifier.fail_show = False
    rounds.tick([failed()], minutes=1)

    assert rounds.notifier.shown_ids == [CARD]
    assert rounds.store().entries()[CARD].sounded_at is not None


def test_a_failed_clear_leaves_the_card_stored_and_is_retried(rounds: Rounds) -> None:
    rounds.tick([failed()])
    rounds.notifier.fail_clear = True

    rounds.tick([stored_unit(state=PLANNED)], minutes=1)
    assert set(rounds.store().entries()) == {CARD}

    rounds.notifier.fail_clear = False
    rounds.tick([stored_unit(state=PLANNED)], minutes=1)

    assert rounds.notifier.cleared == [CARD]
    assert rounds.store().entries() == {}
    assert rounds.notifier.clear_attempts == 2


def test_two_overlapping_reconciliations_show_one_card_once(
    clock: FakeClock, tmp_path: Path
) -> None:
    notifier = FakeNotifier()
    racers = [Rounds(tmp_path / "notifications.json", clock, enabled(), notifier) for _ in range(2)]
    ready = threading.Barrier(len(racers))
    errors: list[BaseException] = []

    def reconcile(racer: Rounds) -> None:
        try:
            ready.wait()
            racer.tick([failed()])
        except BaseException as error:  # noqa: BLE001
            errors.append(error)

    threads = [threading.Thread(target=reconcile, args=(racer,)) for racer in racers]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert notifier.shown_ids == [CARD]
    assert notifier.show_attempts == 1
