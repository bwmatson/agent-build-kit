"""Every Azure DevOps call the pipeline makes, in one place.

What these check is the discipline, not the API: that a call names its
organisation rather than relying on a configured default, that the token is
passed through the environment rather than argv, and above all that an answer
which is not JSON is an error. An unauthenticated Azure DevOps request is
answered with a sign-in page and a 2xx, and read as `{}` that says "no pull
requests" — the failure counter never trips and the pipeline goes quiet with a
clean log.
"""

from __future__ import annotations

import base64
import json
import subprocess
import urllib.error

import pytest

from agent_build_kit.pipeline import az
from agent_build_kit.settings import settings
from tests.forges import azure_answers


def recorded(stdout: str = "", returncode: int = 0):
    calls: list[dict] = []

    def run(args, **kwargs):
        calls.append({"args": args, **kwargs})
        return subprocess.CompletedProcess(args, returncode, stdout, "")

    return run, calls


def test_a_call_names_its_organisation_rather_than_a_configured_default() -> None:
    """`az devops configure --defaults` is global CLI state, and units run
    concurrently: one repo's default would answer another repo's call."""
    run, calls = recorded("[]")

    az.json_out(["repos", "pr", "list"], org="https://dev.azure.com/acme", run=run)

    args = calls[0]["args"]
    assert args[:4] == ["az", "repos", "pr", "list"]
    assert args[args.index("--org") + 1] == "https://dev.azure.com/acme"
    assert "--output" in args and "json" in args


def test_the_token_travels_in_the_environment_not_in_argv(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`ps` shows every argument of every running process, and a build runs
    unattended for hours."""
    monkeypatch.setattr(settings, "ado_pat", "a-secret")
    run, calls = recorded("[]")

    az.json_out(["repos", "pr", "list"], org="https://dev.azure.com/acme", run=run)

    assert "a-secret" not in " ".join(calls[0]["args"])
    assert calls[0]["env"]["AZURE_DEVOPS_EXT_PAT"] == "a-secret"


def test_without_a_token_the_call_falls_back_to_the_az_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both ways of being authenticated have to work: a PAT on a headless box,
    an `az login` session on a workstation."""
    monkeypatch.setattr(settings, "ado_pat", "")
    run, calls = recorded("[]")

    az.json_out(["repos", "pr", "list"], org="https://dev.azure.com/acme", run=run)

    assert "AZURE_DEVOPS_EXT_PAT" not in calls[0]["env"]


def test_an_exported_but_empty_token_is_not_passed_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A variable set to nothing is not a credential. Passed on, `az` attempts
    PAT authentication with an empty token instead of falling back to the
    sign-in session — so a machine that once exported one, and a CI runner
    that sets it blank, would both fail with the session right there."""
    monkeypatch.setenv("AZURE_DEVOPS_EXT_PAT", "")
    monkeypatch.setattr(settings, "ado_pat", "")
    run, calls = recorded("[]")

    az.json_out(["repos", "pr", "list"], org="https://dev.azure.com/acme", run=run)

    assert "AZURE_DEVOPS_EXT_PAT" not in calls[0]["env"]


def test_a_sign_in_page_is_an_error_not_an_empty_answer() -> None:
    """The trap this module exists for: HTML with a 2xx, parsed as nothing,
    reads as "no pull requests" and the poller never backs off."""
    run, _ = recorded("<!DOCTYPE html><html>Sign in to your account")

    with pytest.raises(az.AzError) as refused:
        az.json_out(["repos", "pr", "list"], org="https://dev.azure.com/acme", run=run)

    assert "not JSON" in str(refused.value)


def test_a_failed_call_reports_what_az_said() -> None:
    def run(args, **kwargs):
        return subprocess.CompletedProcess(args, 1, "", "TF401019: repository does not exist")

    with pytest.raises(az.AzError) as refused:
        az.json_out(["repos", "pr", "show"], org="https://dev.azure.com/acme", run=run)

    assert "TF401019" in str(refused.value)


def test_an_empty_answer_is_an_empty_answer() -> None:
    """A command that prints nothing on success — an update, a delete — is not
    a failure, and must not be read as one."""
    run, _ = recorded("")

    assert az.json_out(["repos", "pr", "update"], org="https://dev.azure.com/acme", run=run) is None


def test_the_organisation_url_is_built_from_the_account_name() -> None:
    assert az.org_url("3CInternalAI") == "https://dev.azure.com/3CInternalAI"


def test_the_call_asks_az_for_utf_8() -> None:
    """`az` is a Python program, and on a Windows host it otherwise writes its
    JSON in the console's code page. One em-dash in a review comment then
    arrives as a byte no UTF-8 decoder accepts, and the poll dies on what a
    reviewer happened to type — which is how this was found."""
    run, calls = recorded("[]")

    az.json_out(["repos", "pr", "list"], org="https://dev.azure.com/acme", run=run)

    assert calls[0]["env"]["PYTHONIOENCODING"] == "utf-8"


def test_an_undecodable_byte_costs_a_character_not_the_poll() -> None:
    """Belt and braces beside the environment: whatever a reviewer typed is
    data, and no byte in it may end a tick."""
    run, calls = recorded("[]")

    az.json_out(["repos", "pr", "list"], org="https://dev.azure.com/acme", run=run)

    assert calls[0]["errors"] == "replace"
    assert calls[0]["encoding"] == "utf-8"


# --- the calls `az devops invoke` cannot make ------------------------------------


class FakeResponse:
    def __init__(self, body: str) -> None:
        self.body = body

    def read(self) -> bytes:
        return self.body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *exc) -> None:
        return None


def opener(body: str = "{}", *, seen: list | None = None):
    def open_url(request, timeout=None):
        if seen is not None:
            seen.append(request)
        return FakeResponse(body)

    return open_url


def test_a_pat_authenticates_as_basic(monkeypatch: pytest.MonkeyPatch) -> None:
    """Azure DevOps takes a PAT as the password of an empty user."""
    monkeypatch.setattr(settings, "ado_pat", "a-secret")
    seen: list = []

    az.rest(
        "PATCH", "https://dev.azure.com/acme/_apis/x", payload={"a": 1}, open_url=opener(seen=seen)
    )

    header = seen[0].get_header("Authorization")
    assert header.startswith("Basic ")
    assert base64.b64decode(header.removeprefix("Basic ")).decode() == ":a-secret"


def test_without_a_pat_a_token_is_fetched_through_az(monkeypatch: pytest.MonkeyPatch) -> None:
    """The other supported way to be authenticated: the `az` sign-in session."""
    monkeypatch.setattr(settings, "ado_pat", "")
    run, calls = recorded(azure_answers.access_token("a-token"))
    seen: list = []

    az.rest(
        "PATCH",
        "https://dev.azure.com/acme/_apis/x",
        payload={},
        run=run,
        open_url=opener(seen=seen),
    )

    assert calls[0]["args"][:3] == ["az", "account", "get-access-token"]
    assert seen[0].get_header("Authorization") == "Bearer a-token"


def test_the_method_and_body_are_what_was_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ado_pat", "a-secret")
    seen: list = []

    az.rest(
        "PATCH",
        "https://dev.azure.com/acme/_apis/x",
        payload={"targetRefName": "refs/heads/main"},
        open_url=opener(seen=seen),
    )

    assert seen[0].get_method() == "PATCH"
    assert json.loads(seen[0].data.decode()) == {"targetRefName": "refs/heads/main"}


def test_a_sign_in_page_is_still_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same rule as the CLI path: HTML with a 2xx must not read as an
    empty answer."""
    monkeypatch.setattr(settings, "ado_pat", "a-secret")

    with pytest.raises(az.AzError, match="not JSON"):
        az.rest("PATCH", "https://dev.azure.com/acme/_apis/x", open_url=opener("<!DOCTYPE html>"))


def test_a_refused_call_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ado_pat", "a-secret")

    def refuses(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, None)

    with pytest.raises(az.AzError, match="403"):
        az.rest("PATCH", "https://dev.azure.com/acme/_apis/x", open_url=refuses)


def test_five_calls_ask_the_runner_for_a_token_once(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ado_pat", "")
    run, calls = recorded(azure_answers.access_token("a-token", seconds_left=3600))
    seen: list = []

    for _ in range(5):
        az.rest("GET", "https://dev.azure.com/acme/_apis/x", run=run, open_url=opener(seen=seen))

    assert len([c for c in calls if c["args"][:3] == ["az", "account", "get-access-token"]]) == 1
    assert [r.get_header("Authorization") for r in seen] == ["Bearer a-token"] * 5


def test_a_token_with_thirty_seconds_left_is_fetched_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ado_pat", "")
    answers = iter(
        [
            azure_answers.access_token("old", seconds_left=30),
            azure_answers.access_token("new", seconds_left=3600),
        ]
    )
    calls: list = []

    def run(args, **kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, next(answers), "")

    seen: list = []
    for _ in range(3):
        az.rest("GET", "https://dev.azure.com/acme/_apis/x", run=run, open_url=opener(seen=seen))

    assert len(calls) == 2, "the expiring token was fetched again, the fresh one was kept"
    assert [r.get_header("Authorization") for r in seen] == ["Bearer old", "Bearer new"] + [
        "Bearer new"
    ]


def test_a_personal_access_token_is_never_fetched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ado_pat", "a-secret")
    run, calls = recorded(azure_answers.access_token("a-token"))

    for _ in range(3):
        az.rest("GET", "https://dev.azure.com/acme/_apis/x", run=run, open_url=opener())

    assert calls == []
