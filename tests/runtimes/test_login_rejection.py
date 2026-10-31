"""A `claude` run whose login the service rejects raises `LoginRejected` (spec: login-pause).

The CLI's authentication failure (`Failed to authenticate` with a 401, or `OAuth access token has
expired`) names the account and records the login as rejected; a 401 that is not about the OAuth
login and any other failure stay what they are today.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.claude_account import Account
from agent_build_kit.pipeline import usage_guard
from agent_build_kit.runtimes import AgentRequest, AgentResult, LoginRejected, ToolPolicy
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, login_rejection
from tests.runtimes.claude_cli import FakeClaude, refused
from tests.usage_host import HOUR_MS, Host, ms_from_now, write_credentials

EXPIRED = "Failed to authenticate. API Error: 401 OAuth access token has expired"
EXPIRED_ONLY = "OAuth access token has expired"
REVOKED = (
    'Failed to authenticate. API Error: 401 {"type":"error","error":'
    '{"type":"authentication_error","message":"OAuth token has been revoked"}}'
)
WRONG_KEY = 'API Error: 401 {"type":"error","error":{"message":"invalid x-api-key"}}'
WRONG_KEY_AUTH = "Failed to authenticate. " + WRONG_KEY
OTHER = "Tool execution failed: pytest exited 2"


def _request(
    cwd: Path, account: Account | None, told: list[AgentResult] | None = None
) -> AgentRequest:
    return AgentRequest(
        prompt="Review group 1 of add-marker.",
        role="review",
        cwd=cwd,
        add_dirs=(cwd / "specs",),
        model="opus",
        allowed_tools="Read",
        policy=ToolPolicy(specs_dir=cwd / "specs"),
        on_event=lambda line: None,
        on_result=told.append if told is not None else None,
        account=account,
    )


def _personal(host: Host) -> Account:
    write_credentials(host.home / "second", "token", ms_from_now(HOUR_MS))
    return Account(label="personal", config_dir=host.home / "second")


@pytest.mark.parametrize("said", [EXPIRED, EXPIRED_ONLY, REVOKED])
def test_the_clis_authentication_failure_is_a_login_rejection(said: str) -> None:
    assert login_rejection(said) is True


@pytest.mark.parametrize("said", [WRONG_KEY, WRONG_KEY_AUTH, OTHER, ""])
def test_a_401_about_something_else_and_any_other_failure_are_not(said: str) -> None:
    assert login_rejection(said) is False


def test_a_run_that_meets_the_rejection_raises_naming_the_account_and_records_it(
    host: Host, tmp_path: Path
) -> None:
    personal = _personal(host)
    fake = FakeClaude(stdout=refused(tmp_path, EXPIRED, api_error_status=401), returncode=1)

    with pytest.raises(LoginRejected) as caught:
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path, personal))

    assert isinstance(caught.value, RuntimeError)
    assert caught.value.account == personal
    assert "personal" in str(caught.value)
    note = usage_guard.rejected_login_note(personal)
    assert note is not None
    assert "personal" in note


def test_the_spend_of_the_run_cut_off_is_told_before_the_raise(host: Host, tmp_path: Path) -> None:
    personal = _personal(host)
    told: list[AgentResult] = []
    fake = FakeClaude(stdout=refused(tmp_path, EXPIRED, api_error_status=401), returncode=1)

    with pytest.raises(LoginRejected):
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path, personal, told))

    assert len(told) == 1
    assert not told[0].ok
    assert told[0].turns == 1
    assert told[0].usage is not None


def test_a_401_that_is_not_the_oauth_login_returns_the_failed_result_and_records_nothing(
    host: Host, tmp_path: Path
) -> None:
    personal = _personal(host)
    fake = FakeClaude(stdout=refused(tmp_path, WRONG_KEY, api_error_status=401), returncode=1)

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path, personal))

    assert not result.ok
    assert login_rejection(result.error or "") is False
    assert usage_guard.rejected_login_note(personal) is None
