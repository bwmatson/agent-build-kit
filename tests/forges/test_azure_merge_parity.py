"""The Azure DevOps merge operation is GitHub's under another host (spec: forge-merge)."""

from __future__ import annotations

import inspect

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import MergeRefused, RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost
from tests.forges.azure_rest_host import refusal as azure_refusal
from tests.forges.github_host import GitHubHost, refusal

pytestmark = pytest.mark.usefixtures("rest_env", "github_env")

AZURE = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
GITHUB = RepoId(forge="github", account="example", name="app")
HEAD = "a" * 40
REASON = "Pull Request is not mergeable"


def shape(forge: type) -> list[tuple[str, object, object]]:
    """The arguments a caller passes; `run` is the Azure forge's unused legacy keyword."""
    return [
        (p.name, p.kind, p.default)
        for p in inspect.signature(forge.merge_pr).parameters.values()
        if p.name != "run"
    ]


def test_the_merge_operation_takes_the_same_arguments_and_refuses_the_same_way() -> None:
    assert shape(AzureDevOpsForge) == shape(GitHubForge)
    azure = AzureDevOpsForge(
        http=RestHost(
            azure_answers.pull(),
            refuse={("PATCH", "pullrequests/162"): azure_refusal(409, REASON)},
        )
    )
    github = GitHubForge(
        http=GitHubHost(routes={("PUT", "/repos/example/app/pulls/7/merge"): refusal(405, REASON)})
    )

    with pytest.raises(MergeRefused) as from_azure:
        azure.merge_pr(AZURE, 162, head=HEAD)
    with pytest.raises(MergeRefused) as from_github:
        github.merge_pr(GITHUB, 7, head=HEAD)

    assert type(from_azure.value) is type(from_github.value)
    assert REASON in from_azure.value.reason
    assert REASON in from_github.value.reason


def test_both_forges_declare_that_they_merge() -> None:
    azure = AzureDevOpsForge(http=RestHost())
    github = GitHubForge(http=GitHubHost())

    assert azure.merges is github.merges is True
