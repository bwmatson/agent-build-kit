"""`abk status` prints one pause line per paused account: its account, kind, end and reason (spec:
capacity-checks, one pause per account).

`app` runs on the default account and `platform` on `personal`.
"""

from __future__ import annotations

import argparse
import re

import pytest

from agent_build_kit.cli import pipeline as cli
from tests.cli.test_admission_asks_own_account import (  # noqa: F401 — fixtures
    PERSONAL,
    isolated,
    workspace,
)
from tests.pipeline.test_pause_per_account import (
    DEFAULT_MARKER,
    PERSONAL_MARKER,
    write_marker,
)

pytestmark = pytest.mark.usefixtures("scripted_engine")


@pytest.fixture(autouse=True)
def no_claude_usage(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cli, "current_usage", lambda *a, **k: None)


def pause_lines(inst, capsys: pytest.CaptureFixture[str]) -> list[str]:
    assert cli.cmd_status(argparse.Namespace(), inst) == 0
    return [line for line in capsys.readouterr().out.splitlines() if "paused until" in line]


def test_each_paused_account_has_its_own_line_with_its_kind_and_reason(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, _store = workspace(tmp_path, [])
    write_marker(inst.state_dir / DEFAULT_MARKER, reason="rate limited during one/1")
    write_marker(
        inst.state_dir / PERSONAL_MARKER,
        reason="weekly usage at 93%",
        kind="usage",
        account=PERSONAL,
    )

    default_line, personal_line = sorted(
        pause_lines(inst, capsys), key=lambda each: PERSONAL in each
    )

    assert "default" in default_line and PERSONAL not in default_line
    assert re.search(r"rate[ _]limit", default_line)
    assert "rate limited during one/1" in default_line
    assert PERSONAL in personal_line
    assert "usage" in personal_line
    assert "weekly usage at 93%" in personal_line


def test_an_account_that_is_not_paused_has_no_line(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, _store = workspace(tmp_path, [])
    write_marker(inst.state_dir / PERSONAL_MARKER, reason="rate limited", account=PERSONAL)

    (line,) = pause_lines(inst, capsys)

    assert PERSONAL in line
    assert "default" not in line


def test_a_pause_left_by_an_older_version_without_an_account_shows_as_the_default_accounts(
    tmp_path, capsys: pytest.CaptureFixture[str]
) -> None:
    inst, _store = workspace(tmp_path, [])
    write_marker(inst.state_dir / DEFAULT_MARKER, reason="rate limited during one/1")

    (line,) = pause_lines(inst, capsys)

    assert "default" in line
    assert "rate limited during one/1" in line
