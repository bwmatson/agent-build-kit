"""Reconciling cards from the units: what is called for, shown once, cleared when its reason
ends, reminded, delayed, and never allowed to fail a tick.

The provider is a recording fake, the clock is the pipeline's `spans.clock` seam, and the
units are built in memory. The cases about the round run `run_round` with the command
provider configured and `subprocess.run` as the one boundary faked.
"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.config import NotificationsConfig
from agent_build_kit.installation import Installation
from agent_build_kit.notify.cards import desired_cards
from agent_build_kit.notify.provider import CardKind
from agent_build_kit.notify.store import NotificationStore
from agent_build_kit.pipeline import pause
from agent_build_kit.pipeline.unit_store import Cause, HeldBy, UnitStore
from agent_build_kit.pipeline.units import (
    CLOSED,
    FAILED,
    HELD,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    SATISFIED,
)
from tests import fake_clock
from tests.conftest import make_installation
from tests.factories import stored_unit
from tests.fake_clock import FakeClock
from tests.notify_fakes import FakeNotifier, Rounds, enabled

REVIEW_CARD = "unit:review:add-marker/1"
FAILED_CARD = "unit:failed:add-marker/1"
HELD_CARD = "unit:held:add-marker/1"


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    return fake_clock.install(monkeypatch)


@pytest.fixture
def rounds(clock: FakeClock, tmp_path: Path) -> Rounds:
    return Rounds(tmp_path / "notifications.json", clock, enabled())


def in_review(uid: str = "add-marker/1", **overrides):
    return stored_unit(uid, state=IN_REVIEW, pr=5, **overrides)


def failed(**overrides):
    return stored_unit(state=FAILED, **overrides)


def held(by: HeldBy = HeldBy.NONE, cause: Cause | None = None):
    history = ({"state": "held", "cause": cause.value, "note": "waiting"},) if cause else ()
    return stored_unit(state=HELD, held_by=by, history=history)


# --- what the units call for ----------------------------------------------------------------


def test_a_unit_in_review_with_no_rework_pending_calls_for_a_review_card() -> None:
    (card,) = desired_cards([in_review()])

    assert card.id == REVIEW_CARD
    assert card.kind is CardKind.REVIEW
    assert card.title and card.body and card.link


def test_a_unit_in_review_with_feedback_waiting_calls_for_no_card() -> None:
    assert desired_cards([in_review(feedback="rename the marker")]) == []


def test_a_failed_unit_calls_for_a_failure_card() -> None:
    (card,) = desired_cards([failed()])

    assert (card.id, card.kind) == (FAILED_CARD, CardKind.FAILED)


@pytest.mark.parametrize(
    "unit",
    [held(HeldBy.REVIEW), held(HeldBy.TOOLCHAIN), held(cause=Cause.NEEDS_HUMAN)],
    ids=["review loop", "toolchain", "needs a person"],
)
def test_a_unit_held_for_a_person_calls_for_a_held_card(unit) -> None:
    (card,) = desired_cards([unit])

    assert (card.id, card.kind) == (HELD_CARD, CardKind.HELD)


@pytest.mark.parametrize(
    "unit",
    [held(HeldBy.DEPTH, Cause.DEPTH), held(HeldBy.REVIEWER, Cause.REVIEWER_HOLD)],
    ids=["depth clears itself", "the reviewer's own hold"],
)
def test_a_hold_that_clears_itself_or_is_the_persons_own_calls_for_no_card(unit) -> None:
    assert desired_cards([unit]) == []


@pytest.mark.parametrize("state", [MERGED, RUNNING, PLANNED, CLOSED, SATISFIED])
def test_other_states_call_for_no_card(state) -> None:
    assert desired_cards([stored_unit(state=state)]) == []


def test_each_unit_gets_its_own_card() -> None:
    cards = desired_cards([in_review(), failed(), in_review("other/1")])

    assert sorted(card.id for card in cards) == sorted(
        [REVIEW_CARD, FAILED_CARD, "unit:review:other/1"]
    )


# --- shown once, cleared when the reason ends -----------------------------------------------


def test_a_card_is_shown_once_with_its_id_title_body_and_link(rounds: Rounds) -> None:
    unit = in_review()

    rounds.tick([unit])
    rounds.tick([unit], minutes=1)

    ((id, title, body, link),) = rounds.notifier.shown
    assert id == REVIEW_CARD
    assert title and body and link
    assert rounds.notifier.show_attempts == 1


def test_a_failed_units_card_clears_when_it_is_requeued(rounds: Rounds) -> None:
    rounds.tick([failed()])

    rounds.tick([stored_unit(state=PLANNED)], minutes=1)

    assert rounds.notifier.cleared == [FAILED_CARD]
    assert rounds.store().entries() == {}


def test_a_merged_pull_request_clears_the_review_card(rounds: Rounds) -> None:
    rounds.tick([in_review()])

    rounds.tick([stored_unit(state=MERGED, pr=5)], minutes=1)

    assert rounds.notifier.cleared == [REVIEW_CARD]
    assert rounds.store().entries() == {}


@pytest.mark.parametrize("state", [PLANNED, RUNNING], ids=["rebase", "rework"])
def test_a_unit_sent_back_loses_its_card_and_gets_it_again_on_returning(
    rounds: Rounds, state
) -> None:
    rounds.tick([in_review()])

    rounds.tick([stored_unit(state=state, pr=5, feedback="rename the marker")], minutes=1)
    assert rounds.notifier.cleared == [REVIEW_CARD]

    rounds.tick([in_review()], minutes=1)
    assert rounds.notifier.shown_ids == [REVIEW_CARD, REVIEW_CARD]


def test_feedback_waiting_on_a_unit_still_in_review_clears_its_card(rounds: Rounds) -> None:
    rounds.tick([in_review()])

    rounds.tick([in_review(feedback="rename the marker")], minutes=1)

    assert rounds.notifier.cleared == [REVIEW_CARD]


# --- delay and reminder ---------------------------------------------------------------------


def test_a_card_waits_out_the_delay_before_it_shows(clock: FakeClock, tmp_path: Path) -> None:
    rounds = Rounds(tmp_path / "notifications.json", clock, enabled(delay_minutes=10))

    rounds.tick([failed()])
    rounds.tick([failed()], minutes=9)
    assert rounds.notifier.show_attempts == 0

    rounds.tick([failed()], minutes=1)
    assert rounds.notifier.shown_ids == [FAILED_CARD]


def test_a_unit_that_fails_and_is_requeued_within_the_delay_never_shows(
    clock: FakeClock, tmp_path: Path
) -> None:
    rounds = Rounds(tmp_path / "notifications.json", clock, enabled(delay_minutes=10))

    rounds.tick([failed()])
    rounds.tick([failed()], minutes=5)
    rounds.tick([stored_unit(state=PLANNED)], minutes=1)
    rounds.tick([stored_unit(state=PLANNED)], minutes=30)

    assert (rounds.notifier.show_attempts, rounds.notifier.clear_attempts) == (0, 0)
    assert rounds.store().entries() == {}


def test_a_card_called_for_again_after_a_gap_starts_its_delay_over(
    clock: FakeClock, tmp_path: Path
) -> None:
    rounds = Rounds(tmp_path / "notifications.json", clock, enabled(delay_minutes=10))
    rounds.tick([failed()])
    rounds.tick([failed()], minutes=8)
    rounds.tick([stored_unit(state=PLANNED)], minutes=1)

    rounds.tick([failed()], minutes=1)
    rounds.tick([failed()], minutes=9)

    assert rounds.notifier.show_attempts == 0


def test_a_card_is_sounded_again_after_the_reminder_interval(
    clock: FakeClock, tmp_path: Path
) -> None:
    rounds = Rounds(tmp_path / "notifications.json", clock, enabled(remind_after_minutes=30))
    rounds.tick([failed()])

    rounds.tick([failed()], minutes=29)
    assert len(rounds.notifier.shown) == 1

    rounds.tick([failed()], minutes=2)
    assert rounds.notifier.shown_ids == [FAILED_CARD, FAILED_CARD]

    rounds.tick([failed()], minutes=10)
    assert len(rounds.notifier.shown) == 2

    rounds.tick([failed()], minutes=21)
    assert len(rounds.notifier.shown) == 3
    assert rounds.notifier.cleared == []


# --- off, and a provider that fails ---------------------------------------------------------


def test_a_provider_that_is_off_is_never_called(clock: FakeClock, tmp_path: Path) -> None:
    rounds = Rounds(tmp_path / "notifications.json", clock, NotificationsConfig())

    rounds.tick([in_review(), failed()])
    rounds.tick([stored_unit(state=MERGED)], minutes=60)

    assert (rounds.notifier.show_attempts, rounds.notifier.clear_attempts) == (0, 0)
    assert not (tmp_path / "notifications.json").exists()


def test_a_show_that_raises_is_logged_and_tried_again_next_tick(rounds: Rounds) -> None:
    rounds.notifier.fail_show = True

    rounds.tick([failed()])
    assert FAILED_CARD in "".join(rounds.lines)

    rounds.notifier.fail_show = False
    rounds.tick([failed()], minutes=1)

    assert rounds.notifier.shown_ids == [FAILED_CARD]
    assert rounds.notifier.show_attempts == 2


def test_a_failure_on_one_card_does_not_stop_the_others(clock: FakeClock, tmp_path: Path) -> None:
    class FailsOne(FakeNotifier):
        def show(self, id: str, title: str, body: str, link: str) -> None:
            if id == FAILED_CARD:
                raise RuntimeError("no")
            super().show(id, title, body, link)

    rounds = Rounds(tmp_path / "notifications.json", clock, enabled(), FailsOne())

    rounds.tick([failed(), in_review("other/1")])

    assert rounds.notifier.shown_ids == ["unit:review:other/1"]


# --- the round --------------------------------------------------------------------------------


@pytest.fixture
def inst(tmp_path: Path) -> Installation:
    return make_installation(
        tmp_path,
        planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")},
        notifications={
            "provider": "command",
            "delay_minutes": 0,
            "command": {"show": "notify-send {title} {link}", "clear": "dismiss {id}"},
        },
    )


@pytest.fixture
def host(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Every program the round runs, answered with exit 0: the command provider's boundary."""
    calls: list[list[str]] = []

    def run(argv, *args, **kwargs):
        calls.append(list(argv))
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(cli, "poll_all", lambda inst, **kwargs: None)
    monkeypatch.setattr(cli, "fetch_all", lambda inst: None)
    monkeypatch.setattr(cli, "has_thread", lambda inst, unit_id: False)
    return calls


def a_round(inst: Installation, store: UnitStore) -> None:
    cli.run_round(inst, store, building=set(), started=set(), only=frozenset(), submit=False)


def notified(host: list[list[str]]) -> list[list[str]]:
    return [argv for argv in host if argv[0] == "notify-send"]


def test_a_round_shows_a_card_for_a_unit_in_review_once(
    inst: Installation, tmp_path: Path, host: list[list[str]]
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([in_review()])

    a_round(inst, store)
    a_round(inst, store)

    assert len(notified(host)) == 1
    assert (tmp_path / "notifications.json").is_file()


def test_a_round_with_no_notifications_section_runs_nothing_and_writes_nothing(
    tmp_path: Path, host: list[list[str]]
) -> None:
    inst = make_installation(
        tmp_path, planning={"state_dir": ".", "worktree_root": str(tmp_path.parent / "trees")}
    )
    store = UnitStore(tmp_path / "units.json")
    store.upsert([in_review()])

    a_round(inst, store)

    assert host == []
    assert not (tmp_path / "notifications.json").exists()


def test_a_round_that_stops_at_a_usage_pause_still_shows_a_failure(
    inst: Installation, tmp_path: Path, host: list[list[str]]
) -> None:
    store = UnitStore(tmp_path / "units.json")
    store.upsert([failed()])
    pause.pause_until(
        datetime.now(UTC) + timedelta(hours=1),
        reason="the model refused",
        marker=tmp_path / "paused.json",
        kind="rate_limit",
    )

    a_round(inst, store)

    assert len(notified(host)) == 1


def test_a_provider_that_cannot_run_leaves_the_round_and_the_unit_unharmed(
    inst: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host: list[list[str]]
) -> None:
    def missing(argv, *args, **kwargs):
        raise FileNotFoundError(argv[0])

    monkeypatch.setattr(subprocess, "run", missing)
    store = UnitStore(tmp_path / "units.json")
    store.upsert([failed()])

    a_round(inst, store)

    assert store.get("add-marker/1").state == FAILED
    entries = NotificationStore(tmp_path / "notifications.json").entries()
    assert all(entry.sounded_at is None for entry in entries.values())
