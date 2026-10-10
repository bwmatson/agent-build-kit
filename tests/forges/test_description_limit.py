"""A forge states the longest description its host takes; it does not cut to it.

The description is fitted once, to the lowest limit across the registered
hosts, where the pipeline hands it to a forge, so a host sends what it is
given. Both hosts are the REST stand-ins, so what is checked is the request
the forge sends.
"""

from __future__ import annotations

import httpx
import pytest

from agent_build_kit import forges
from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost
from tests.forges.github_host import GitHubHost, answer
from tests.forges.stand_in import StandInForge

AZURE_REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
GITHUB_REPO = RepoId(forge="github", account="example", name="app")
GITHUB_PULLS = "/repos/example/app/pulls"


def lined(count: int, width: int = 60) -> str:
    """`count` distinct lines."""
    return "\n".join(f"line {number:04d} " + "x" * width for number in range(count))


def azure_sent(host: RestHost) -> str:
    [call] = host.writes()
    return call.body["description"]


def github_created() -> httpx.Response:
    return answer(
        {
            "number": 7,
            "node_id": "PR_kwDOAAAAAc00000007",
            "state": "open",
            "html_url": "https://github.com/example/app/pull/7",
            "head": {"ref": "spec/add-marker/1"},
            "base": {"ref": "main"},
        },
        201,
    )


# --- the limits -------------------------------------------------------------------


def test_the_limits_are_the_hosts() -> None:
    assert GitHubForge().description_limit == 65_536
    assert AzureDevOpsForge().description_limit == 4_000


def test_the_stand_in_states_a_positive_limit() -> None:
    assert StandInForge().description_limit > 0


def test_the_effective_limit_is_the_lowest_across_the_registered_hosts() -> None:
    declared = [forges.get(name).description_limit for name in forges.names()]

    assert forges.description_limit() == min(declared)
    assert forges.description_limit() == 4_000


def test_a_host_with_a_lower_limit_lowers_the_effective_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(forges.get("github"), "description_limit", 1_500)

    assert forges.description_limit() == 1_500


def test_a_host_with_a_higher_limit_leaves_the_effective_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(forges.get("github"), "description_limit", 200_000)

    assert forges.description_limit() == 4_000


# --- no host cuts a description ---------------------------------------------------


@pytest.mark.usefixtures("rest_env")
def test_azure_creating_sends_the_body_it_was_given() -> None:
    host = RestHost()
    body = lined(100)
    assert len(body) > 4_000

    AzureDevOpsForge(http=host).create_pr(
        AZURE_REPO, head="spec/add-marker/1", base="main", title="T", body=body
    )

    assert azure_sent(host) == body


@pytest.mark.usefixtures("github_env")
def test_github_creating_sends_the_body_it_was_given() -> None:
    host = GitHubHost(routes={("POST", GITHUB_PULLS): github_created()})
    body = lined(1_200)
    assert len(body) > 65_536

    GitHubForge(http=host).create_pr(
        GITHUB_REPO, head="spec/add-marker/1", base="main", title="t", body=body
    )

    [call] = host.calls("POST", GITHUB_PULLS)
    assert call.body["body"] == body


@pytest.mark.usefixtures("rest_env")
def test_azure_updating_sends_the_body_it_was_given() -> None:
    host = RestHost(azure_answers.OPEN)
    body = lined(100)

    AzureDevOpsForge(http=host).update_pr(AZURE_REPO, 162, body=body)

    assert azure_sent(host) == body


@pytest.mark.usefixtures("github_env")
def test_github_updating_sends_the_body_it_was_given() -> None:
    route = ("PATCH", f"{GITHUB_PULLS}/7")
    host = GitHubHost(routes={route: answer({"number": 7})})
    body = lined(1_200)

    GitHubForge(http=host).update_pr(GITHUB_REPO, 7, body=body)

    [call] = host.calls(*route)
    assert call.body["body"] == body


@pytest.mark.usefixtures("rest_env")
def test_a_fenced_body_is_sent_without_a_closer_added() -> None:
    host = RestHost()
    body = "<details>\n\n```\n" + lined(100)

    AzureDevOpsForge(http=host).create_pr(
        AZURE_REPO, head="spec/add-marker/1", base="main", title="T", body=body
    )

    assert azure_sent(host) == body
