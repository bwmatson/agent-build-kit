"""GitHub merges by squash with the approved head as a guard (spec: forge-merge).

The host is the GitHub stand-in, so what is checked is the request the forge sends and what
it makes of the answers GitHub gives to the merge route."""

from __future__ import annotations

import httpx
import pytest

from agent_build_kit.forges.base import MergeRefused, RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.transport import HostError
from tests.forges.github_host import GitHubHost, answer, refusal

pytestmark = pytest.mark.usefixtures("github_env")

REPO = RepoId(forge="github", account="example", name="app")
BASE = "/repos/example/app"
MERGE = f"{BASE}/pulls/7/merge"
HEAD = "a" * 40
MERGED = "b" * 40


def forge(host: GitHubHost) -> GitHubForge:
    return GitHubForge(http=host)


def merged() -> httpx.Response:
    return answer({"sha": MERGED, "merged": True, "message": "Pull Request successfully merged"})


def test_the_forge_declares_that_it_merges() -> None:
    assert forge(GitHubHost()).merges is True


def test_the_request_names_the_squash_method_and_the_approved_head() -> None:
    host = GitHubHost(routes={("PUT", MERGE): merged()})

    forge(host).merge_pr(REPO, 7, head=HEAD)

    [call] = host.calls("PUT", MERGE)
    assert call.body["merge_method"] == "squash"
    assert call.body["sha"] == HEAD


def test_a_merge_returns_the_merge_commit() -> None:
    host = GitHubHost(routes={("PUT", MERGE): merged()})

    assert forge(host).merge_pr(REPO, 7, head=HEAD) == MERGED


@pytest.mark.parametrize(
    "reply, message",
    [
        pytest.param(
            refusal(409, "Head branch was modified. Review and try the merge again."),
            "Head branch was modified",
            id="head-moved",
        ),
        pytest.param(
            refusal(405, "Pull Request is not mergeable"),
            "Pull Request is not mergeable",
            id="not-mergeable",
        ),
        pytest.param(
            refusal(405, "At least 1 approving review is required by reviewers with write access."),
            "approving review is required",
            id="rule-blocks",
        ),
        pytest.param(
            refusal(
                422,
                "Repository rule violations found",
                [{"message": "Changes must be made through a pull request"}],
            ),
            "Repository rule violations found",
            id="ruleset-blocks",
        ),
        pytest.param(refusal(405, "Pull Request is closed"), "Pull Request is closed", id="closed"),
    ],
)
def test_a_host_that_will_not_merge_is_a_refusal_carrying_its_message(
    reply: httpx.Response, message: str
) -> None:
    host = GitHubHost(routes={("PUT", MERGE): reply})

    with pytest.raises(MergeRefused) as refused:
        forge(host).merge_pr(REPO, 7, head=HEAD)

    assert message in refused.value.reason
    assert len(host.calls("PUT", MERGE)) == 1


@pytest.mark.parametrize(
    "reply",
    [
        pytest.param(refusal(500, "Server Error"), id="500"),
        pytest.param(refusal(502, "Bad Gateway"), id="502"),
        pytest.param(httpx.ConnectError("no route to host"), id="unreachable"),
    ],
)
def test_any_other_failure_is_the_ordinary_transport_failure(
    reply: httpx.Response | Exception,
) -> None:
    host = GitHubHost(routes={("PUT", MERGE): reply})

    with pytest.raises(HostError):
        forge(host).merge_pr(REPO, 7, head=HEAD)


# --- the commit a merged pull request produced ------------------------------------


def test_the_commit_of_a_merged_pull_request_is_read_from_the_host() -> None:
    pull = {"number": 7, "state": "closed", "merged": True, "merge_commit_sha": MERGED}
    host = GitHubHost(routes={("GET", f"{BASE}/pulls/7"): answer(pull)})

    assert forge(host).merge_commit(REPO, 7) == MERGED


def test_a_pull_request_that_is_not_merged_has_no_commit() -> None:
    pull = {"number": 7, "state": "open", "merged": False, "merge_commit_sha": "c" * 40}
    host = GitHubHost(routes={("GET", f"{BASE}/pulls/7"): answer(pull)})

    assert forge(host).merge_commit(REPO, 7) is None
