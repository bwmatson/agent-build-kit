"""The login refresh runs under the account it is for (spec: login-refresh).

The account is a labelled `Account` with a directory of its own, never `settings.claude_home`,
which is the default account's path. Only the endpoint, the home directory and the `claude`
process are faked.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import urllib.error
from datetime import UTC, datetime
from email.message import Message
from io import BytesIO
from pathlib import Path

import pytest

from agent_build_kit.claude_account import VARIABLE, Account
from agent_build_kit.installation import Installation
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.runtimes import claude_code
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime
from agent_build_kit.runtimes.claude_code import refresh_login as real_refresh_login
from agent_build_kit.settings import settings
from tests.call_rows import agent_rows
from tests.runtimes.claude_cli import no_agent
from tests.usage_host import Host, payload

HOUR_MS = 3_600_000


def ms_from_now(offset_ms: int) -> int:
    return int(datetime.now(UTC).timestamp() * 1000) + offset_ms


def write_credentials(directory: Path, token: str, expires_at_ms: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / ".credentials.json").write_text(
        json.dumps({"claudeAiOauth": {"accessToken": token, "expiresAt": expires_at_ms}})
    )


def unauthorized() -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        usage_guard.USAGE_URL, 401, "Unauthorized", Message(), BytesIO(b"")
    )


class Claude:
    """The `claude` process: records the environment it was started with and, as the real one
    does for the account it is told, writes a fresh token there (or leaves the file alone)."""

    def __init__(self, *, writes: str | None) -> None:
        self.writes = writes
        self.envs: list[dict[str, str] | None] = []

    def __call__(self, argv, **kwargs) -> subprocess.CompletedProcess[str]:
        env = kwargs.get("env")
        self.envs.append(env)
        if self.writes is not None and env is not None:
            write_credentials(Path(env[VARIABLE]), self.writes, ms_from_now(HOUR_MS))
        return subprocess.CompletedProcess(argv, 0, "", "")


@pytest.fixture
def personal(host: Host, monkeypatch: pytest.MonkeyPatch) -> Account:
    """An account labelled `personal` with an expired saved token, beside a default account
    whose token is good, and no token in the environment."""
    monkeypatch.delenv("CLAUDE_CODE_OAUTH_TOKEN")
    write_credentials(host.home / ".claude", "default-token", ms_from_now(HOUR_MS))
    directory = host.home / "personal"
    write_credentials(directory, "old-token", ms_from_now(-HOUR_MS))
    return Account(label="personal", config_dir=directory)


def sent_tokens(host: Host, monkeypatch: pytest.MonkeyPatch) -> list[str | None]:
    sent: list[str | None] = []
    answer = host.urlopen

    def urlopen(request, timeout=None):
        sent.append(request.get_header("Authorization"))
        return answer(request, timeout)

    monkeypatch.setattr("urllib.request.urlopen", urlopen)
    return sent


def test_a_labelled_accounts_refresh_runs_in_its_directory_and_the_retry_carries_the_new_token(
    host: Host, personal: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude = Claude(writes="new-token")
    monkeypatch.setattr(
        claude_code, "refresh_login", lambda account=None: real_refresh_login(account, run=claude)
    )
    sent = sent_tokens(host, monkeypatch)
    host.answers = [unauthorized(), payload()]

    with usage_guard.on_account(personal):
        reading = usage_guard.read_live_usage()

    assert reading is not None
    assert claude.envs == [{**os.environ, VARIABLE: str(personal.config_dir)}]
    assert sent == ["Bearer old-token", "Bearer new-token"]


def test_the_refresh_is_for_the_account_given_not_the_setting(
    host: Host, personal: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "claude_home", host.home / "elsewhere")
    claude = Claude(writes=None)

    real_refresh_login(personal, run=claude)

    assert claude.envs == [{**os.environ, VARIABLE: str(personal.config_dir)}]


def test_a_refresh_that_leaves_the_token_names_the_account_in_the_failure(
    host: Host, personal: Account, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    claude = Claude(writes=None)
    monkeypatch.setattr(
        claude_code, "refresh_login", lambda account=None: real_refresh_login(account, run=claude)
    )
    host.answers = [unauthorized()]

    with caplog.at_level(logging.WARNING), usage_guard.on_account(personal):
        reading = usage_guard.read_live_usage()

    assert reading is None
    assert host.asked == 1, "the unchanged token is not sent again"
    assert any("personal" in record.getMessage() for record in caplog.records)


def test_the_runtimes_usage_status_refreshes_under_the_account_in_force(
    host: Host, personal: Account, monkeypatch: pytest.MonkeyPatch
) -> None:
    claude = Claude(writes="new-token")
    monkeypatch.setattr(
        claude_code, "refresh_login", lambda account=None: real_refresh_login(account, run=claude)
    )
    host.answers = [unauthorized(), payload(session=30.0)]

    with usage_guard.on_account(personal):
        status = ClaudeCodeRuntime(execute=no_agent).get_usage_status()

    assert status is not None
    assert claude.envs == [{**os.environ, VARIABLE: str(personal.config_dir)}]


def test_the_ledger_row_of_a_labelled_refresh_still_names_the_runtime(
    workspace: Installation, tmp_path: Path
) -> None:
    claude = Claude(writes=None)

    real_refresh_login(Account(label="personal", config_dir=tmp_path / "personal"), run=claude)

    assert claude.envs[0] is not None
    (row,) = agent_rows(workspace)
    assert (row["node"], row["unit"], row["role"], row["model"]) == (
        "login_refresh",
        "",
        "generic",
        "haiku",
    )
    assert row["outcome"] == "ok"
