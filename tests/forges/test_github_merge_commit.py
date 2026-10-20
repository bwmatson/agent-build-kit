"""GitHub answers the commit a merged pull request produced from its own merge record
(spec: review-outcomes). The host is the GitHub stand-in."""

from __future__ import annotations

import pytest

from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.forges.github_host import GitHubHost, answer, refusal

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
PULL = ("GET", "/repos/example/app/pulls/7")


def test_a_missing_pull_request_answers_empty() -> None:
    host = GitHubHost(routes={PULL: refusal(404, "Not Found")})

    assert GitHubForge(http=host).merge_commit(REPO, 7) is None


def test_a_closed_unmerged_pull_request_answers_empty() -> None:
    pull = {"number": 7, "state": "closed", "merged": False, "merge_commit_sha": "c" * 40}
    host = GitHubHost(routes={PULL: answer(pull)})

    assert GitHubForge(http=host).merge_commit(REPO, 7) is None
