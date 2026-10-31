"""A `claude` run whose login the service rejects raises `LoginRejected` (spec: login-pause).

The CLI's authentication failure (`Failed to authenticate` with a 401, or `OAuth access token has
expired`) names the account; a 401 that is not about the OAuth login and any other failure stay
what they are today.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.claude_account import Account
from agent_build_kit.runtimes import AgentRequest, LoginRejected, ToolPolicy
from agent_build_kit.runtimes.claude_code import ClaudeCodeRuntime, login_rejection
from tests.runtimes.claude_cli import FakeClaude, refused

EXPIRED = "Failed to authenticate. API Error: 401 OAuth access token has expired"
EXPIRED_ONLY = "OAuth access token has expired"
WRONG_KEY = 'API Error: 401 {"type":"error","error":{"message":"invalid x-api-key"}}'
OTHER = "Tool execution failed: pytest exited 2"


def _request(cwd: Path, account: Account | None) -> AgentRequest:
    return AgentRequest(
        prompt="Review group 1 of add-marker.",
        role="review",
        cwd=cwd,
        add_dirs=(cwd / "specs",),
        model="opus",
        allowed_tools="Read",
        policy=ToolPolicy(specs_dir=cwd / "specs"),
        on_event=lambda line: None,
        account=account,
    )


@pytest.mark.parametrize("said", [EXPIRED, EXPIRED_ONLY])
def test_the_clis_authentication_failure_is_a_login_rejection(said: str) -> None:
    assert login_rejection(said) is True


@pytest.mark.parametrize("said", [WRONG_KEY, OTHER, ""])
def test_a_401_about_something_else_and_any_other_failure_are_not(said: str) -> None:
    assert login_rejection(said) is False


def test_a_run_that_meets_the_rejection_raises_naming_the_account(tmp_path: Path) -> None:
    personal = Account(label="personal", config_dir=tmp_path / "second")
    fake = FakeClaude(stdout=refused(tmp_path, EXPIRED, api_error_status=401), returncode=1)

    with pytest.raises(LoginRejected) as caught:
        ClaudeCodeRuntime(execute=fake).run(_request(tmp_path, personal))

    assert isinstance(caught.value, RuntimeError)
    assert caught.value.account == personal
    assert "personal" in str(caught.value)


def test_a_401_that_is_not_the_oauth_login_returns_the_failed_result(tmp_path: Path) -> None:
    fake = FakeClaude(stdout=refused(tmp_path, WRONG_KEY, api_error_status=401), returncode=1)

    result = ClaudeCodeRuntime(execute=fake).run(_request(tmp_path, None))

    assert not result.ok
    assert login_rejection(result.error or "") is False
