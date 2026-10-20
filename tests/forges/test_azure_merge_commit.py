"""Azure DevOps answers the commit a completed pull request produced from its own
merge record, and empty where it cannot say (spec: review-outcomes)."""

from __future__ import annotations

import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import RepoId
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost, refusal

pytestmark = pytest.mark.usefixtures("rest_env")

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
PULL = "pullrequests/162"
MERGED = "b" * 40


def test_an_abandoned_pull_request_with_a_merge_commit_answers_empty() -> None:
    abandoned = azure_answers.pull(status="abandoned", lastMergeCommit=dict(commitId=MERGED))

    assert AzureDevOpsForge(http=RestHost(abandoned)).merge_commit(REPO, 162) is None


def test_a_missing_pull_request_answers_empty() -> None:
    host = RestHost(azure_answers.pull(), refuse={("GET", PULL): refusal(404, "not found")})

    assert AzureDevOpsForge(http=host).merge_commit(REPO, 162) is None
