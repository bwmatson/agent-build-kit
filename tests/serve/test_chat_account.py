"""The sessions page lists, finds and resumes in the account directory: the one it lists
`projects` from is the one the `claude --resume` it runs is told (spec: claude-account)."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from agent_build_kit.installation import Installation
from agent_build_kit.settings import settings
from tests.chat_serving import claude_session_file, turn, use_claude
from tests.runtimes.claude_cli import finished_build

pytestmark = pytest.mark.serial

ACCOUNT_SESSION = "0b7e1d52-9c3a-4f8e-b1d6-2a5c7e9f0d61"
DEFAULT_SESSION = "6d2a8f14-3e5b-4c7a-9f0e-1b8d3c6a2e71"
VARIABLE = "CLAUDE_CONFIG_DIR"


@pytest.fixture
def account(inst: Installation, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """The setting is `<tmp>/account`, holding one session; the default directory, which is
    `<tmp>/home/.claude`, holds another."""
    directory = tmp_path / "account"
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(settings, "claude_home", directory)
    claude_session_file(directory, ACCOUNT_SESSION, inst.root, title="In the account")
    claude_session_file(home / ".claude", DEFAULT_SESSION, inst.root, title="In the default")
    return directory


def test_the_listed_session_of_the_account_is_found_and_resumed_in_the_account(
    account: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch, inst: Installation
) -> None:
    fake = use_claude(monkeypatch, finished_build(inst.root, "Looked."))

    listed = api.get("/api/sessions").json()["sessions"]
    found = api.get(f"/api/sessions/claude_code/{ACCOUNT_SESSION}")
    turn(
        api,
        f"/api/sessions/claude_code/{ACCOUNT_SESSION}/continue",
        {"tab": "t1", "prompt": "Carry on."},
    )

    assert [s["id"] for s in listed] == [ACCOUNT_SESSION]
    assert found.status_code == 200
    argv, _ = fake.calls[0]
    assert argv[argv.index("--resume") + 1] == ACCOUNT_SESSION
    env = fake.envs[0]
    assert env is not None
    assert env[VARIABLE] == str(account)


def test_a_session_of_the_default_account_is_not_found_while_an_account_is_set(
    account: Path, api: httpx.Client, monkeypatch: pytest.MonkeyPatch, inst: Installation
) -> None:
    fake = use_claude(monkeypatch, finished_build(inst.root, "Looked."))

    missing = api.post(
        f"/api/sessions/claude_code/{DEFAULT_SESSION}/continue",
        json={"tab": "t1", "prompt": "Carry on."},
    )
    absent = api.get(f"/api/sessions/claude_code/{DEFAULT_SESSION}")

    assert missing.status_code == 404
    assert absent.status_code == 404
    assert not fake.calls
    # The account's own session is still resumed, so it is the account that answers 404.
    turn(
        api,
        f"/api/sessions/claude_code/{ACCOUNT_SESSION}/continue",
        {"tab": "t1", "prompt": "Carry on."},
    )
    assert fake.envs[0] is not None and fake.envs[0][VARIABLE] == str(account)
