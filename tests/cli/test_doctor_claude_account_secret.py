"""`abk doctor` prints nothing of `auth status` but whether it is logged in, warns about a
token beside an account, and adds no account line for a runtime without one."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from agent_build_kit.cli.doctor import run_doctor
from tests.account_settings import Configure
from tests.cli.claude_auth_fakes import FakeClaude, account_lines, in_planning_env, said
from tests.cli.test_doctor import (  # noqa: F401 — fixture
    Answers,
    select_runtime,
    workspace,
)
from tests.factories import which_all
from tests.runtimes.selectable import SelectableRuntime, select

TOKEN = "sk-ant-oat01-" + "x" * 40
EMAIL = "someone@example.com"


def test_no_other_field_of_the_answer_is_printed_logged_or_sent_to_the_error_stream(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    configure: Configure,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    directory = tmp_path / "second"
    directory.mkdir()
    in_planning_env(workspace, configure, dotenv={"ABK_CLAUDE_HOME": str(directory)})
    run = FakeClaude(extra={"accessToken": TOKEN, "email": EMAIL, "authMethod": "claude.ai"})

    with caplog.at_level(logging.DEBUG):
        checks = account_lines(workspace, run)

    streams = capsys.readouterr()
    seen = said(checks) + streams.out + streams.err + caplog.text
    assert checks
    assert TOKEN not in seen and EMAIL not in seen and "claude.ai" not in seen


def test_a_token_beside_an_account_warns_without_printing_its_value(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    configure: Configure,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "second"
    directory.mkdir()
    in_planning_env(workspace, configure, dotenv={"ABK_CLAUDE_HOME": str(directory)})
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", TOKEN)

    checks = account_lines(workspace, FakeClaude())

    warned = [c for c in checks if c.status == "warn" and "CLAUDE_CODE_OAUTH_TOKEN" in said([c])]
    assert len(warned) == 1
    assert "usage guard" in said(warned)
    assert TOKEN not in said(checks)


def test_a_runtime_that_reports_no_account_has_no_account_line_and_claude_code_has_one(
    workspace: Path,  # noqa: F811 — fixture
    tmp_path: Path,
    configure: Configure,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    directory = tmp_path / "second"
    directory.mkdir()
    in_planning_env(workspace, configure, dotenv={"ABK_CLAUDE_HOME": str(directory)})
    assert account_lines(workspace, FakeClaude())

    select(monkeypatch, SelectableRuntime("plain"))
    select_runtime(workspace, "plain")
    checks = run_doctor(workspace / "abk.yaml", run=Answers(), which=which_all)

    assert [c for c in checks if c.name == "runtime"]
    assert not [c for c in checks if "account" in c.name]
