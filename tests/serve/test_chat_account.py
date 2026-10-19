"""The sessions page lists, finds and resumes in the account directory: the one it lists
`projects` from is the one the `claude --resume` it runs is told (spec: claude-account)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from agent_build_kit.claude_account import VARIABLE
from agent_build_kit.installation import Installation
from agent_build_kit.settings import settings
from tests.chat_serving import claude_session_file, turn, use_claude
from tests.runtimes.claude_cli import finished_build


@pytest.fixture
def account_session(new_session_id: Callable[[], str]) -> str:
    return new_session_id()


@pytest.fixture
def default_session(new_session_id: Callable[[], str]) -> str:
    return new_session_id()


@pytest.fixture
def account(
    inst: Installation,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    account_session: str,
    default_session: str,
) -> Path:
    """The setting is `<tmp>/account`, holding one session; the default directory, which is
    `<tmp>/home/.claude`, holds another."""
    directory = tmp_path / "account"
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(settings, "claude_home", directory)
    claude_session_file(directory, account_session, inst.root, title="In the account")
    claude_session_file(home / ".claude", default_session, inst.root, title="In the default")
    return directory


def test_the_listed_session_of_the_account_is_found_and_resumed_in_the_account(
    account: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
    inst: Installation,
    account_session: str,
) -> None:
    fake = use_claude(monkeypatch, finished_build(inst.root, "Looked."))

    listed = api.get("/api/sessions").json()["sessions"]
    found = api.get(f"/api/sessions/claude_code/{account_session}")
    turn(
        api,
        f"/api/sessions/claude_code/{account_session}/continue",
        {"tab": "t1", "prompt": "Carry on."},
    )

    assert [s["id"] for s in listed] == [account_session]
    assert found.status_code == 200
    argv, _ = fake.calls[0]
    assert argv[argv.index("--resume") + 1] == account_session
    env = fake.envs[0]
    assert env is not None
    assert env[VARIABLE] == str(account)


def test_a_session_of_the_default_account_is_not_found_while_an_account_is_set(
    account: Path,
    api: httpx.Client,
    monkeypatch: pytest.MonkeyPatch,
    inst: Installation,
    account_session: str,
    default_session: str,
) -> None:
    fake = use_claude(monkeypatch, finished_build(inst.root, "Looked."))

    missing = api.post(
        f"/api/sessions/claude_code/{default_session}/continue",
        json={"tab": "t1", "prompt": "Carry on."},
    )
    absent = api.get(f"/api/sessions/claude_code/{default_session}")

    assert missing.status_code == 404
    assert absent.status_code == 404
    assert not fake.calls
    # The account's own session is still resumed, so it is the account that answers 404.
    turn(
        api,
        f"/api/sessions/claude_code/{account_session}/continue",
        {"tab": "t1", "prompt": "Carry on."},
    )
    assert fake.envs[0] is not None and fake.envs[0][VARIABLE] == str(account)
