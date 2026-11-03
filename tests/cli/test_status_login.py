"""`abk status` says how many units an account's rejected login has paused (spec: login-pause).
The line about the login itself and its command is the one the usage guard already prints."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from agent_build_kit import claude_account
from agent_build_kit.cli import build_parser
from agent_build_kit.cli import pipeline as cli
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.pipeline.unit_store import Cause
from agent_build_kit.pipeline.units import RUNNING
from tests import fake_clock
from tests.cli.test_admission_asks_own_account import PERSONAL
from tests.cli.usage_pause_support import unit, workspace
from tests.usage_host import HOUR_MS, Host, ms_from_now, write_credentials


def status_lines(inst, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert cli.cmd_status(build_parser().parse_args(["status"]), inst) == 0
    return capsys.readouterr().out.splitlines()


def test_the_status_names_the_rejected_login_and_the_units_paused_for_it(
    tmp_path: Path,
    host: Host,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clock = fake_clock.install(monkeypatch)
    inst, store = workspace(
        tmp_path, [unit("a/1", "platform"), unit("b/1", "platform"), unit("c/1", "app")]
    )
    host.keep_in(inst.state_dir)
    monkeypatch.setattr(cli, "current_usage", lambda: None)
    account = claude_account.resolve(inst, PERSONAL)
    assert account.config_dir is not None
    write_credentials(account.config_dir, "old-token", ms_from_now(HOUR_MS))
    usage_guard.record_login_rejected(account)
    for unit_id in ("a/1", "b/1"):
        store.set_state(unit_id, RUNNING, branch=f"spec/{unit_id}", cause=Cause.LOGIN)
        store.set_usage_pause(unit_id, clock.now() + timedelta(hours=1), cause=Cause.LOGIN)

    lines = status_lines(inst, capsys)

    assert any("account personal" in line and "login is rejected" in line for line in lines)
    assert any("account personal: 2 units paused for the login" in line for line in lines)


def test_nothing_is_said_of_units_paused_when_no_login_is_rejected(
    tmp_path: Path,
    host: Host,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    inst, store = workspace(tmp_path, [unit("a/1", "app")])
    host.keep_in(inst.state_dir)
    monkeypatch.setattr(cli, "current_usage", lambda: None)

    assert not any("paused for the login" in line for line in status_lines(inst, capsys))
