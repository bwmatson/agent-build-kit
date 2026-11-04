"""GitHub answers the commit a merged pull request produced from the GraphQL merge commit, which
the REST API version does not remove (spec: github-merge-commit). The host is the GitHub
stand-in."""

from __future__ import annotations

import pytest

from agent_build_kit.forges.base import RepoId
from agent_build_kit.forges.github import GitHubForge
from tests.forges import github_answers
from tests.forges.github_host import GitHubHost, answer
from tests.forges.github_routes import GRAPHQL

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
MERGED = "b" * 40
MERGED_AT = "2026-10-01T12:00:00Z"


def merged(number: int, commit: str = MERGED) -> dict:
    return github_answers.pull(number, state="MERGED", merged_at=MERGED_AT, merge_commit=commit)


def test_a_merged_pull_request_answers_its_merge_commit_in_one_request() -> None:
    host = GitHubHost(merged(7))

    assert GitHubForge(http=host).merge_commit(REPO, 7) == MERGED

    [call] = host.seen
    assert call.path == GRAPHQL
    assert "mergeCommit" in call.query


def test_the_rest_pull_request_is_not_read() -> None:
    host = GitHubHost(merged(7))

    GitHubForge(http=host).merge_commit(REPO, 7)

    assert host.calls("GET") == []


@pytest.mark.parametrize(
    "node",
    [
        pytest.param(github_answers.pull(7), id="open"),
        pytest.param(github_answers.pull(7, state="CLOSED"), id="closed-unmerged"),
    ],
)
def test_a_pull_request_that_is_not_merged_answers_empty(node: dict) -> None:
    assert GitHubForge(http=GitHubHost(node)).merge_commit(REPO, 7) is None


def test_an_unknown_pull_request_answers_empty() -> None:
    host = GitHubHost(github_answers.pull(1))

    assert GitHubForge(http=host).merge_commit(REPO, 7) is None
    assert len(host.seen) == 1


def test_a_null_pull_request_with_no_error_answers_empty() -> None:
    reply = answer({"data": {"repository": {"pullRequest": None}}})
    host = GitHubHost(routes={("POST", GRAPHQL): reply})

    assert GitHubForge(http=host).merge_commit(REPO, 7) is None


# --- the listing ------------------------------------------------------------------


def test_the_listing_carries_a_merged_pull_request_s_commit_into_its_snapshot() -> None:
    host = GitHubHost(merged(7), github_answers.pull(8))

    pulls = {pull.number: pull for pull in GitHubForge(http=host).list_prs(REPO)}

    assert pulls[7].merge_commit == MERGED
    assert pulls[8].merge_commit is None
    assert len(host.seen) == 1, "the commit comes with the listing, not a request of its own"
