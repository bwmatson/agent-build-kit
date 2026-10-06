"""Both ways of being authenticated work over REST, and an answer that is not
JSON is an authentication failure rather than an empty listing."""

from __future__ import annotations

import base64
import subprocess

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.transport import AuthError, credential_for
from agent_build_kit.settings import settings
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost, refusal
from tests.forges.mock_host import sign_in_page

pytestmark = pytest.mark.usefixtures("rest_env")

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
RESOURCE = "499b84ac-1321-427f-aa17-267ca6975798"


class Az:
    """`az`, as a subprocess.run stand-in, answering `account get-access-token`."""

    def __init__(self, token: str = "tok-az", code: int = 0) -> None:
        self.token = token
        self.code = code
        self.commands: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        self.commands.append(list(argv))
        out = f"{self.token}\n" if not self.code else ""
        return subprocess.CompletedProcess(argv, self.code, out, "ERROR: not logged in")


def sent_with(host: RestHost) -> set[str]:
    return {call.authorization for call in host.seen}


# --- a personal access token ------------------------------------------------------


def test_a_pat_is_a_basic_credential_with_an_empty_user() -> None:
    host = RestHost(azure_answers.OPEN)

    AzureDevOpsForge(http=host).list_prs(REPO)

    expected = "Basic " + base64.b64encode(b":pat-secret").decode()
    assert sent_with(host) == {expected}


def test_a_pat_never_starts_the_cli() -> None:
    az = Az()
    host = RestHost(azure_answers.OPEN)

    AzureDevOpsForge(http=host).list_prs(REPO, run=az)

    assert az.commands == []


def test_a_pat_is_never_in_a_url_or_a_body() -> None:
    host = RestHost(azure_answers.OPEN)

    AzureDevOpsForge(http=host).post_comment(REPO, 162, body="hello")

    assert all("pat-secret" not in str(call.request.url) for call in host.seen)
    assert all("pat-secret" not in str(call.body) for call in host.seen)


# --- the logged-in CLI as a source ------------------------------------------------


def test_without_a_pat_the_cli_session_is_the_source_of_a_bearer_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ado_pat", "")
    az = Az("tok-az")
    host = RestHost(azure_answers.OPEN)

    AzureDevOpsForge(http=host).list_prs(REPO, run=az)

    assert sent_with(host) == {"Bearer tok-az"}
    [command] = az.commands
    assert command[:3] == ["az", "account", "get-access-token"]
    assert command[command.index("--resource") + 1] == RESOURCE
    assert all("tok-az" not in arg for arg in command)


def test_the_cli_is_read_once_while_its_token_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ado_pat", "")
    az = Az()
    forge = AzureDevOpsForge(http=RestHost(azure_answers.OPEN))

    forge.list_prs(REPO, run=az)
    forge.list_prs(REPO, run=az)

    assert len(az.commands) == 1


def test_the_credential_names_where_it_came_from(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ado_pat", "")

    credentials = credential_for("azure_devops", "acme", run=Az("tok-az"))

    assert (credentials.scheme, credentials.token, credentials.owner) == (
        "Bearer",
        "tok-az",
        "acme",
    )
    assert "az account get-access-token" in credentials.source


def test_the_setting_is_a_credential_too() -> None:
    credentials = credential_for("azure_devops", "acme", run=Az())

    assert f"{credentials.scheme} {credentials.token}" == (
        "Basic " + base64.b64encode(b":pat-secret").decode()
    )


def test_no_credential_says_what_to_set_or_run(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ado_pat", "")

    with pytest.raises(AuthError) as caught:
        credential_for("azure_devops", "acme", run=Az(code=1))

    message = str(caught.value)
    assert "acme" in message
    assert "AZURE_DEVOPS_EXT_PAT" in message
    assert "az login" in message


# --- what a refusal looks like ----------------------------------------------------


def test_a_sign_in_page_is_an_authentication_error_not_an_empty_listing() -> None:
    """Azure DevOps answers an unauthenticated request with a sign-in page and a
    200. Read as empty, the poller's failure counter never trips and the
    pipeline goes quiet with a clean log."""
    host = RestHost()
    host.refuse[("GET", "pullrequests")] = sign_in_page()

    with pytest.raises(AuthError, match="JSON"):
        AzureDevOpsForge(http=host).list_prs(REPO)


@pytest.mark.parametrize("status", [401, 403])
def test_a_refused_credential_is_an_authentication_error(status: int) -> None:
    host = RestHost()
    host.refuse[("GET", "pullrequests")] = refusal(status, "TF400813: not authorized")

    with pytest.raises(AuthError):
        AzureDevOpsForge(http=host).list_prs(REPO)


def test_a_sign_in_page_on_a_write_is_an_authentication_error() -> None:
    host = RestHost(azure_answers.OPEN)
    host.refuse[("PATCH", "pullrequests/162")] = sign_in_page()

    with pytest.raises(AuthError):
        AzureDevOpsForge(http=host).close_pr(REPO, 162)


def test_a_rejected_cli_token_is_read_again_and_the_call_made_once_more(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ado_pat", "")
    az = Az("tok-old")
    host = RestHost(azure_answers.OPEN)
    forge = AzureDevOpsForge(http=host)
    forge.list_prs(REPO, run=az)

    host.rejected_tokens.add("tok-old")  # it expired
    az.token = "tok-new"
    forge.post_comment(REPO, 162, body="hello", run=az)

    assert len(az.commands) == 2
    assert host.seen[-1].authorization == "Bearer tok-new"
    assert host.writes()[-1].body is not None


def test_a_cli_token_rejected_again_after_the_fresh_read_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ado_pat", "")
    az = Az("tok-bad")
    host = RestHost(azure_answers.OPEN)
    host.rejected_tokens.add("tok-bad")

    with pytest.raises(AuthError):
        AzureDevOpsForge(http=host).list_prs(REPO, run=az)

    assert len(az.commands) == 2, "one fresh read, not a loop"


def test_a_rejected_pat_is_not_retried() -> None:
    az = Az()
    host = RestHost(azure_answers.OPEN, refuse={("GET", "pullrequests"): refusal(401, "no")})

    with pytest.raises(AuthError):
        AzureDevOpsForge(http=host).list_prs(REPO, run=az)

    assert len(host.calls("GET", "pullrequests")) == 1
    assert az.commands == []
