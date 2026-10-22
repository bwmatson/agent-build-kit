"""The review labels reach each host through the forge's own label calls (spec: review-triage)."""

from __future__ import annotations

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.pipeline.verdict import ReviewTier
from agent_build_kit.pipeline.vocabulary import review_label, review_label_names
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost
from tests.forges.github_host import GitHubHost

GITHUB = RepoId(forge="github", account="example", name="app")
AZURE = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
LIGHT = review_label(ReviewTier.LIGHT)
FULL = review_label(ReviewTier.FULL)
AUTO = review_label(ReviewTier.AUTO)


@pytest.mark.usefixtures("github_env")
def test_github_creates_and_sets_a_review_label_by_its_own_name() -> None:
    host = GitHubHost(repo_labels=[("bug", "d73a4a", "Not working")], pr_labels={7: ["bug"]})

    GitHubForge(http=host).set_exclusive_label(GITHUB, 7, LIGHT, family=review_label_names())

    assert set(host.pr_labels[7]) == {"bug", LIGHT.name}
    assert host.repo_labels[LIGHT.name]["color"] == LIGHT.color
    assert host.repo_labels[LIGHT.name]["description"] == LIGHT.description


@pytest.mark.usefixtures("github_env")
def test_github_replacing_a_review_label_leaves_the_others_off() -> None:
    host = GitHubHost(
        repo_labels=[
            (AUTO.name, AUTO.color, AUTO.description or ""),
            (LIGHT.name, LIGHT.color, LIGHT.description or ""),
            ("bug", "d73a4a", "x"),
        ],
        pr_labels={7: [AUTO.name, LIGHT.name, "bug"]},
    )

    GitHubForge(http=host).set_exclusive_label(GITHUB, 7, FULL, family=review_label_names())

    assert set(host.pr_labels[7]) == {"bug", FULL.name}


@pytest.mark.usefixtures("rest_env")
def test_azure_sets_a_review_label_by_its_own_name() -> None:
    host = RestHost(azure_answers.OPEN, labels={162: ["unrelated"]})

    AzureDevOpsForge(http=host).set_exclusive_label(AZURE, 162, LIGHT, family=review_label_names())

    assert sorted(host.label_names(162)) == sorted(["unrelated", LIGHT.name])


@pytest.mark.usefixtures("rest_env")
def test_azure_replacing_a_review_label_leaves_the_others_off() -> None:
    host = RestHost(azure_answers.OPEN, labels={162: [LIGHT.name, AUTO.name, "unrelated"]})

    AzureDevOpsForge(http=host).set_exclusive_label(AZURE, 162, FULL, family=review_label_names())

    assert sorted(host.label_names(162)) == sorted(["unrelated", FULL.name])
