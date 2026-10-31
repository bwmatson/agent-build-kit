"""A unit whose usage pause has not reached its time is not resumed to ask the guard again; it is
resumed at its time, and when a fresh reading allows the step (spec: usage-pause-slots, a paused
unit is not resumed early).

`platform` runs on the `personal` account, whose reading is full while `app`'s is open, so the
round goes on and a resume is what it chooses not to make."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline.usage_guard import Decision
from tests import fake_clock
from tests.cli.test_admission_asks_own_account import PERSONAL, Accounts
from tests.cli.usage_pause_support import (
    isolate_round,
    pause_for_usage,
    started_by,
    unit,
    with_threads,
    workspace,
)

PAUSED = "paused/1"
FRESH = "fresh/1"
SIZE = 321


@pytest.fixture
def clock(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> fake_clock.FakeClock:
    return fake_clock.install(monkeypatch)


@pytest.fixture
def accounts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: fake_clock.FakeClock):
    answers = isolate_round(tmp_path, monkeypatch)
    answers.full = {PERSONAL}
    return answers


@pytest.fixture
def paused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accounts: Accounts,
    clock: fake_clock.FakeClock,
):
    """A workspace with `PAUSED` (on the full account) paused for three hours, and a unit of
    the open account to start."""
    inst, store = workspace(tmp_path, [unit(PAUSED, "platform"), unit(FRESH, "app")])
    pause_for_usage(store, PAUSED, clock.now() + timedelta(hours=3))
    with_threads(monkeypatch, PAUSED)
    return inst, store


def test_a_round_before_the_time_with_the_reading_unchanged_does_not_resume_the_unit(
    paused, accounts: Accounts
) -> None:
    inst, store = paused

    ready = started_by(inst, store)

    assert PAUSED not in ready
    assert FRESH in ready


def test_the_unit_is_resumed_when_its_time_comes(
    paused, accounts: Accounts, clock: fake_clock.FakeClock
) -> None:
    inst, store = paused
    assert PAUSED not in started_by(inst, store)

    clock.advance(3 * 3600 + 60)

    assert PAUSED in started_by(inst, store)


def test_the_unit_is_resumed_before_its_time_when_a_fresh_reading_allows_the_step(
    paused, accounts: Accounts
) -> None:
    inst, store = paused
    assert PAUSED not in started_by(inst, store)

    accounts.full = set()

    assert PAUSED in started_by(inst, store)


def test_a_dry_run_asks_about_a_paused_unit_without_recording_an_allowance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: fake_clock.FakeClock
) -> None:
    """The guard is asked whether a paused unit would be resumed, which only reads: a dry run
    records no allowance for a unit it does not build, as the admission of a new unit does not."""
    isolate_round(tmp_path, monkeypatch)
    inside = [0]
    asked: list[tuple[int | None, bool]] = []

    @contextmanager
    def quiet() -> Iterator[None]:
        inside[0] += 1
        try:
            yield
        finally:
            inside[0] -= 1

    def decide(*, estimated_lines: int | None = None, **_: object) -> Decision:
        asked.append((estimated_lines, inside[0] > 0))
        if estimated_lines != SIZE:
            return Decision(may_start=True, reason="plenty")
        return Decision(
            may_start=False,
            reason="session usage at 93%",
            resume_at=clock.now() + timedelta(hours=3),
        )

    monkeypatch.setattr(cli, "decide_start", decide)
    monkeypatch.setattr(cli, "not_recording", quiet)
    inst, store = workspace(tmp_path, [unit(PAUSED, estimated_lines=SIZE), unit(FRESH)])
    pause_for_usage(store, PAUSED, clock.now() + timedelta(hours=3))
    with_threads(monkeypatch, PAUSED)

    started_by(inst, store, dry_run=True)

    assert (SIZE, True) in asked
    assert (SIZE, False) not in asked
