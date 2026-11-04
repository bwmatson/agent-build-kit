"""A rejected login pauses an account's units and resumes them when it is renewed (spec:
login-pause): the gate refuses the account's agent steps, a step that meets the rejection pauses
and does not fail, a renewed login clears the marker after one probe, a repeated rejection with
the same credentials does not probe again, a unit failed on the rejection earlier is paused for
it, and a unit that has never started is not admitted on the account."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.stack_runner import RunStatus
from agent_build_kit.pipeline.unit_store import Cause, UnitStore
from agent_build_kit.pipeline.units import FAILED, PLANNED, RUNNING
from agent_build_kit.runtimes.base import LoginRejected
from tests import fake_clock
from tests.cli.test_admission_asks_own_account import PERSONAL, Accounts, waits
from tests.cli.usage_pause_support import isolate_round, started_by, unit, with_threads, workspace
from tests.graph_driver import fresh, tick
from tests.usage_host import HOUR_MS, Host, ms_from_now, write_credentials

LINE = "account personal: the login is rejected (HTTP 401) after a refresh; run claude auth login"
EXPIRED_401 = (
    "RuntimeError: claude exited 1: Failed to authenticate. "
    "API Error: 401 OAuth access token has expired"
)
PAUSED = "paused/1"


# --- the gate and the node -------------------------------------------------------------


def test_a_refusal_for_the_login_pauses_the_unit_with_the_cause_login(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)

    outcome = tick(tmp_path, recorder, login_rejected=lambda: LINE)

    stored = recorder.store.get("add-marker/1")
    assert outcome.status == RunStatus.PAUSED
    assert (stored.state, stored.cause) == (RUNNING, Cause.LOGIN)
    assert stored.paused_until is not None, "counted as in progress, holding no worker"


def test_no_rejection_leaves_the_gate_to_usage_alone(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)

    tick(tmp_path, recorder, login_rejected=lambda: None)

    assert recorder.store.get("add-marker/1").cause is not Cause.LOGIN


def test_a_step_that_meets_the_rejection_leaves_the_unit_paused_and_not_failed(
    tmp_path: Path,
) -> None:
    recorder = fresh(tmp_path)

    def rejected(*args: object, **kwargs: object) -> str:
        raise LoginRejected(claude_account.Account.default(), "401 OAuth access token has expired")

    with pytest.raises(LoginRejected):
        tick(tmp_path, recorder, run=rejected)

    stored = recorder.store.get("add-marker/1")
    assert stored.state != FAILED
    assert (stored.state, stored.cause) == (RUNNING, Cause.LOGIN)
    assert stored.paused_until is not None


def test_the_login_pause_ends_when_the_gate_later_finds_no_rejection(tmp_path: Path) -> None:
    recorder = fresh(tmp_path)
    tick(tmp_path, recorder, login_rejected=lambda: LINE)

    tick(tmp_path, recorder, login_rejected=lambda: None)

    stored = recorder.store.get("add-marker/1")
    assert stored.paused_until is None
    assert stored.cause is not Cause.LOGIN


# --- the rounds --------------------------------------------------------------------------


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> fake_clock.FakeClock:
    return fake_clock.install(monkeypatch)


@pytest.fixture
def accounts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clock: fake_clock.FakeClock
) -> Accounts:
    return isolate_round(tmp_path, monkeypatch)


def personal_of(inst: Installation) -> claude_account.Account:
    return claude_account.resolve(inst, PERSONAL)


def mark_rejected(inst: Installation) -> claude_account.Account:
    """The personal account's login is recorded as rejected for its credentials as they are."""
    account = personal_of(inst)
    assert account.config_dir is not None
    write_credentials(account.config_dir, "old-token", ms_from_now(HOUR_MS))
    usage_guard.record_login_rejected(account)
    assert usage_guard.rejected_login_note(account) is not None
    return account


def renew(account: claude_account.Account) -> None:
    assert account.config_dir is not None
    write_credentials(account.config_dir, "new-token", ms_from_now(3 * HOUR_MS))


def pause_for_login(store: UnitStore, unit_id: str, clock: fake_clock.FakeClock) -> None:
    store.set_state(unit_id, RUNNING, branch=f"spec/{unit_id}", cause=Cause.LOGIN)
    store.set_usage_pause(unit_id, clock.now() + timedelta(hours=1), cause=Cause.LOGIN)


@pytest.fixture
def paused(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accounts: Accounts,
    clock: fake_clock.FakeClock,
    host: Host,
):
    """`PAUSED` on the personal account, paused for its rejected login, and a fresh unit of the
    default account."""
    inst, store = workspace(tmp_path, [unit(PAUSED, "platform"), unit("fresh/1", "app")])
    host.keep_in(inst.state_dir)
    mark_rejected(inst)
    pause_for_login(store, PAUSED, clock)
    with_threads(monkeypatch, PAUSED)
    monkeypatch.setattr(cli, "login_probe", lambda account: pytest.fail("no probe expected"))
    return inst, store


def test_a_unit_paused_for_the_login_is_not_resumed_while_the_marker_stands(
    paused, clock: fake_clock.FakeClock
) -> None:
    inst, store = paused
    clock.advance(3 * 3600)

    ready = started_by(inst, store)

    assert PAUSED not in ready, "even past its time: it ends on a change, not at a time"
    assert "fresh/1" in ready, "another account's unit goes on"


def test_a_renewed_login_whose_probe_passes_clears_the_marker_and_resumes_the_unit(
    paused, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store = paused
    probed: list[str] = []
    monkeypatch.setattr(cli, "login_probe", lambda account: probed.append(account.label) or True)
    renew(personal_of(inst))

    ready = started_by(inst, store)

    assert probed == [PERSONAL], "one probe"
    assert usage_guard.rejected_login_note(personal_of(inst)) is None
    assert PAUSED in ready


def test_a_renewed_login_whose_probe_fails_keeps_the_marker_for_the_new_credentials(
    paused, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store = paused
    probes: list[str] = []
    monkeypatch.setattr(cli, "login_probe", lambda account: probes.append(account.label) or False)
    renew(personal_of(inst))

    first = started_by(inst, store)
    second = started_by(inst, store)

    assert usage_guard.rejected_login_note(personal_of(inst)) is not None
    assert PAUSED not in first and PAUSED not in second
    assert probes == [PERSONAL], "the same credentials are not probed again"


def test_the_same_credentials_are_never_probed(paused) -> None:
    inst, store = paused

    started_by(inst, store)
    started_by(inst, store)
    # `paused` makes the probe fail the test if it is called.


def test_a_rejection_with_the_same_expiry_pauses_again_without_a_probe(
    paused, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store = paused
    probes: list[str] = []
    monkeypatch.setattr(cli, "login_probe", lambda account: probes.append(account.label) or True)
    account = personal_of(inst)

    usage_guard.record_login_rejected(account)  # the resumed unit is rejected again
    ready = started_by(inst, store)

    assert probes == []
    assert PAUSED not in ready


# --- a unit failed on the rejection before this change ----------------------------------


def failed_on_the_login(store: UnitStore, unit_id: str) -> None:
    store.set_state(unit_id, FAILED, branch=f"spec/{unit_id}", note=EXPIRED_401)


def test_a_unit_failed_on_the_rejection_is_requeued_once_while_its_login_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accounts: Accounts,
    clock: fake_clock.FakeClock,
    host: Host,
) -> None:
    inst, store = workspace(
        tmp_path,
        [
            unit("old/1", "platform"),
            unit("other/1", "platform"),
            unit("app/1", "app"),
            unit("later/1", "platform"),
        ],
    )
    host.keep_in(inst.state_dir)
    mark_rejected(inst)
    failed_on_the_login(store, "old/1")
    store.set_state("other/1", FAILED, branch="spec/other/1", note="RuntimeError: a test failed")
    store.set_state("app/1", FAILED, branch="spec/app/1", note=EXPIRED_401)
    asked: list[tuple[str, str]] = []

    def requeue(inst, unit_id, mode, **kwargs):  # the real one resumes the unit's thread
        asked.append((unit_id, mode))
        store.set_state(unit_id, PLANNED, note="requeued")
        return 0

    monkeypatch.setattr(cli, "requeue", requeue)

    first = cli.record_login_pauses(inst)
    second = cli.record_login_pauses(inst)

    assert first == ["old/1"], "the personal account's; the default account's login is not rejected"
    assert asked == [("old/1", "resume")], "through the requeue that puts the thread right"
    assert second == [], "once: it is no longer failed"
    assert store.get("other/1").state == FAILED, "a failure that is not the login stays"
    assert store.get("app/1").state == FAILED


def test_nothing_is_requeued_when_the_login_is_not_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, accounts: Accounts, host: Host
) -> None:
    inst, store = workspace(tmp_path, [unit("old/1", "platform")])
    host.keep_in(inst.state_dir)
    failed_on_the_login(store, "old/1")
    monkeypatch.setattr(cli, "requeue", lambda *a, **k: pytest.fail("not requeued"))

    assert cli.record_login_pauses(inst) == []


# --- admission ---------------------------------------------------------------------------


@pytest.fixture
def waiting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    accounts: Accounts,
    clock: fake_clock.FakeClock,
    host: Host,
):
    """A never-started and a started unit of each account, with the personal login rejected."""
    inst, store = workspace(
        tmp_path,
        [
            unit("new-personal/1", "platform"),
            unit("new-default/1", "app"),
            unit("old-personal/1", "platform"),
        ],
    )
    # Started once: it has a branch, and is back to `planned` (a restack or a requeue).
    store.set_state("old-personal/1", PLANNED, branch="spec/old-personal/1")
    host.keep_in(inst.state_dir)
    mark_rejected(inst)
    monkeypatch.setattr(cli, "login_probe", lambda account: pytest.fail("no probe expected"))
    return inst, store


def test_a_never_started_unit_is_not_admitted_on_a_rejected_account(waiting) -> None:
    inst, store = waiting

    ready = started_by(inst, store)

    assert "new-personal/1" not in ready
    assert "new-default/1" in ready
    reason = waits(inst)["new-personal/1"].detail
    assert "personal" in reason and "claude auth login" in reason


def test_a_started_unit_is_not_refused_by_the_start_decision(waiting) -> None:
    inst, store = waiting

    ready = started_by(inst, store)

    assert "old-personal/1" not in waits(inst), waits(inst)
    assert "old-personal/1" in ready


def test_the_account_is_admitted_again_when_the_marker_is_cleared(
    waiting, monkeypatch: pytest.MonkeyPatch
) -> None:
    inst, store = waiting
    monkeypatch.setattr(cli, "login_probe", lambda account: True)
    renew(personal_of(inst))

    assert "new-personal/1" in started_by(inst, store)
