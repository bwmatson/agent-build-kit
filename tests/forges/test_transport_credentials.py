"""Credentials by owner: a setting, else the logged-in CLI, once per owner."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest

from agent_build_kit.forges.transport import (
    AuthError,
    Transport,
    clear_credentials,
    credential_for,
)
from agent_build_kit.settings import settings
from tests.forges.mock_host import MockHost, ok


class Cli:
    """`gh`, as a subprocess.run stand-in: a token per logged-in owner."""

    def __init__(self, tokens: dict[str, str]):
        self.tokens = tokens
        self.commands: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        owner = argv[argv.index("--user") + 1]
        token = self.tokens.get(owner)
        if token is None:
            return subprocess.CompletedProcess(argv, 1, "", "no account")
        return subprocess.CompletedProcess(argv, 0, f"{token}\n", "")


@pytest.fixture(autouse=True)
def fresh(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(settings, "gh_token", "")
    clear_credentials()
    yield
    clear_credentials()


def test_the_setting_wins_over_the_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "gh_token", "tok-setting")
    cli = Cli({"example": "tok-cli"})

    credentials = credential_for("github", "example", run=cli)

    assert credentials.token == "tok-setting"
    assert credentials.owner == "example"
    assert cli.commands == []


def test_without_a_setting_the_cli_is_the_source() -> None:
    cli = Cli({"example": "tok-cli"})

    credentials = credential_for("github", "example", run=cli)

    assert credentials.token == "tok-cli"
    assert "gh auth token" in credentials.source
    assert cli.commands[0][:3] == ["gh", "auth", "token"]


def test_the_cli_is_read_once_per_owner_and_cached() -> None:
    cli = Cli({"example": "tok-a", "acme": "tok-b"})

    for _ in range(3):
        credential_for("github", "example", run=cli)
    credential_for("github", "acme", run=cli)

    assert len(cli.commands) == 2


def test_no_token_appears_in_any_argument_list() -> None:
    cli = Cli({"example": "tok-secret"})
    host = MockHost(ok({}))

    credentials = credential_for("github", "example", run=cli)
    Transport("https://api.example.test", credentials, transport=host).request("GET", "/user")

    assert all("tok-secret" not in arg for argv in cli.commands for arg in argv)
    assert host.requests[0].headers["authorization"] == "Bearer tok-secret"


def test_two_owners_at_once_each_use_their_own() -> None:
    cli = Cli({"example": "tok-example", "acme": "tok-acme"})
    host = MockHost(ok({}))

    def call(owner: str) -> str:
        credentials = credential_for("github", owner, run=cli)
        Transport("https://api.example.test", credentials, transport=host).request(
            "GET", f"/{owner}"
        )
        return credentials.token

    with ThreadPoolExecutor(max_workers=2) as pool:
        tokens = list(pool.map(call, ["example", "acme"] * 4))

    assert tokens == ["tok-example", "tok-acme"] * 4
    sent = {r.url.path: r.headers["authorization"] for r in host.requests}
    assert sent == {"/example": "Bearer tok-example", "/acme": "Bearer tok-acme"}
    assert settings.gh_token == ""  # nothing global was switched


def test_no_credential_names_the_owner_and_the_sources_tried() -> None:
    with pytest.raises(AuthError) as caught:
        credential_for("github", "acme", run=Cli({}))

    message = str(caught.value)
    assert "acme" in message
    assert "gh auth token" in message
    assert "GH_TOKEN" in message
