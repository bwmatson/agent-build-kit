"""A forge states the longest status description its host takes; it does not cut to it.

A status description is fitted once, to the lowest status limit across the
registered hosts, where the pipeline builds it, so a host sends what it is
given. Both hosts are the REST stand-ins, so what is checked is the request
the forge sends.
"""

from __future__ import annotations

import pytest

from agent_build_kit import forges
from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.pipeline.tier2 import Tier2Result, post_status
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost
from tests.forges.github_host import GitHubHost, answer
from tests.forges.stand_in import StandInForge

AZURE_REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
GITHUB_REPO = RepoId(forge="github", account="example", name="app")
STATUS_ROUTE = ("POST", "/repos/example/app/statuses/abc1234def")


def result() -> Tier2Result:
    return Tier2Result(
        sha="abc1234def",
        passed=4,
        failed=0,
        skipped=1,
        duration_seconds=12.5,
        command="uv run pytest -m local_stack",
        output="4 passed, 1 skipped in 12.50s",
    )


# --- the limits -------------------------------------------------------------------


def test_the_status_limits_are_the_hosts() -> None:
    assert GitHubForge().status_limit == 139
    assert AzureDevOpsForge().status_limit == 950


def test_every_registered_host_declares_a_status_limit() -> None:
    for name in forges.names():
        assert forges.get(name).status_limit > 0, name


def test_the_effective_status_limit_is_the_lowest_across_the_registered_hosts() -> None:
    declared = [forges.get(name).status_limit for name in forges.names()]

    assert forges.status_limit() == min(declared)
    assert forges.status_limit() == 139


def test_a_host_with_a_lower_status_limit_lowers_the_effective_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(forges.get("azure_devops"), "status_limit", 60)

    assert forges.status_limit() == 60


# --- no host cuts a status description --------------------------------------------


@pytest.mark.usefixtures("github_env")
def test_github_sends_the_status_description_it_was_given() -> None:
    host = GitHubHost(routes={STATUS_ROUTE: answer({"id": 1, "state": "success"}, 201)})

    GitHubForge(http=host).post_status(
        GITHUB_REPO, sha="abc1234def", ok=True, context="local/tier2", description="x" * 200
    )

    [call] = host.calls(*STATUS_ROUTE)
    assert call.body["description"] == "x" * 200


@pytest.mark.usefixtures("rest_env")
def test_azure_sends_the_status_description_it_was_given() -> None:
    host = RestHost(azure_answers.OPEN)

    AzureDevOpsForge(http=host).post_status(
        AZURE_REPO,
        sha="abc123",
        ok=True,
        context="local/tier2",
        description="x" * 1_200,
        head="spec/add-marker/1",
    )

    assert host.writes()[0].body["description"] == "x" * 1_200


# --- the description is fitted to the lowest limit before a host is handed it -----


def test_a_status_description_within_the_lowest_limit_reaches_the_host_unchanged() -> None:
    forge = StandInForge()

    post_status(forge, forge.repo_id(), result())

    [posted] = forge.statuses
    assert posted["description"] == "4 passed, 0 failed in 12s"
    assert len(posted["description"]) <= forges.status_limit()


def test_a_status_description_over_the_lowest_limit_is_fitted_to_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(forges.get("github"), "status_limit", 12)
    forge = StandInForge()

    post_status(forge, forge.repo_id(), result())

    [posted] = forge.statuses
    assert 0 < len(posted["description"]) <= 12
    assert posted["description"].startswith("4 passed")


def test_the_same_status_description_goes_to_every_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(forges.get("azure_devops"), "status_limit", 15)
    first, second = StandInForge(), StandInForge()
    second.status_limit = 5_000

    post_status(first, first.repo_id(), result())
    post_status(second, second.repo_id(), result())

    assert first.statuses[0]["description"] == second.statuses[0]["description"]
    assert len(first.statuses[0]["description"]) <= 15
