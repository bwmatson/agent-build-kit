"""Azure DevOps completes a pull request by squash with the approved head as a guard
(spec: forge-merge).

The host is the REST stand-in, so what is checked is the request the forge sends and
what it makes of the answers the service gives to the completion call."""

from __future__ import annotations

import httpx
import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import MergeRefused, RepoId
from agent_build_kit.forges.resilient import ResilientForge, RetryPolicy
from agent_build_kit.forges.transport import HostError
from tests.fake_clock import FakeClock
from tests.forges import azure_answers
from tests.forges.azure_rest_host import RestHost, answer, refusal

pytestmark = pytest.mark.usefixtures("rest_env")

REPO = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
PULL = "pullrequests/162"
HEAD = "a" * 40
MOVED = "c" * 40
MERGED = "b" * 40


def forge(host: httpx.BaseTransport) -> AzureDevOpsForge:
    return AzureDevOpsForge(http=host)


def active(**overrides: object) -> dict:
    """An open pull request whose source head is the approved commit."""
    return azure_answers.pull(
        lastMergeSourceCommit=dict(commitId=HEAD),
        lastMergeCommit=dict(commitId=MERGED),
        **overrides,
    )


def completed() -> dict:
    return active(status="completed", closedDate="2026-09-11T22:35:38.150623+00:00")


class Flaky(httpx.BaseTransport):
    """The service dropping the answer to the completion call: the first completion is
    answered 503, after it reached the service (`lands`) or before it did."""

    def __init__(self, host: RestHost, *, lands: bool) -> None:
        self.host = host
        self.lands = lands
        self.failed = False

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "PATCH" and not self.failed:
            self.failed = True
            if self.lands:
                self.host.handle_request(request)
            return refusal(503, "The service is unavailable.")
        return self.host.handle_request(request)


def layer(inner: AzureDevOpsForge) -> ResilientForge:
    clock = FakeClock()
    return ResilientForge(
        inner, RetryPolicy(attempts=3, deadline_seconds=1000.0), clock, clock.advance
    )


def test_the_forge_declares_that_it_merges() -> None:
    assert forge(RestHost(active())).merges is True


def test_the_request_completes_by_squash_with_the_approved_head() -> None:
    host = RestHost(active())

    forge(host).merge_pr(REPO, 162, head=HEAD)

    [call] = host.calls("PATCH", PULL)
    assert call.body["status"] == "completed"
    assert call.body["lastMergeSourceCommit"] == dict(commitId=HEAD)
    assert call.body["completionOptions"]["mergeStrategy"] == "squash"


def test_a_completed_answer_returns_the_merge_commit() -> None:
    host = RestHost(active())

    assert forge(host).merge_pr(REPO, 162, head=HEAD) == MERGED


def test_a_pull_request_left_active_with_a_reason_is_a_refusal_carrying_it() -> None:
    stuck = active(
        mergeStatus="rejectedByPolicy",
        mergeFailureMessage="Required reviewers have not approved the pull request.",
    )
    host = RestHost(stuck, refuse={("PATCH", PULL): answer(stuck)})

    with pytest.raises(MergeRefused) as refused:
        forge(host).merge_pr(REPO, 162, head=HEAD)

    assert "Required reviewers have not approved" in refused.value.reason
    assert len(host.calls("PATCH", PULL)) <= 1


@pytest.mark.parametrize("status", ["abandoned", "completed"])
def test_a_pull_request_that_is_not_active_is_a_refusal(status: str) -> None:
    closed = active(status=status)
    message = "TF401072: The pull request is not active."
    host = RestHost(closed, refuse={("PATCH", PULL): refusal(409, message)})

    with pytest.raises(MergeRefused):
        forge(host).merge_pr(REPO, 162, head=HEAD)


def test_a_head_that_moved_is_a_refusal() -> None:
    pushed = active(lastMergeSourceCommit=dict(commitId=MOVED))
    message = "TF401178: The source branch has changed since the merge was approved."
    host = RestHost(pushed, refuse={("PATCH", PULL): refusal(409, message)})

    with pytest.raises(MergeRefused):
        forge(host).merge_pr(REPO, 162, head=HEAD)


def test_a_failure_after_the_service_completed_returns_the_commit_it_finds() -> None:
    host = RestHost(active())

    merged = layer(forge(Flaky(host, lands=True))).merge_pr(REPO, 162, head=HEAD)

    assert merged == MERGED
    assert len(host.calls("PATCH", PULL)) == 1


def test_a_failure_before_the_service_did_anything_is_tried_again() -> None:
    host = RestHost(active())

    merged = layer(forge(Flaky(host, lands=False))).merge_pr(REPO, 162, head=HEAD)

    assert merged == MERGED
    assert len(host.calls("PATCH", PULL)) == 1
    assert host.calls("GET", PULL)


def test_an_unwrapped_transient_failure_is_the_ordinary_transport_failure() -> None:
    host = RestHost(active(), refuse={("PATCH", PULL): refusal(503, "down")})

    with pytest.raises(HostError):
        forge(host).merge_pr(REPO, 162, head=HEAD)


def test_the_commit_of_a_completed_pull_request_is_read_from_the_host() -> None:
    assert forge(RestHost(completed())).merge_commit(REPO, 162) == MERGED


def test_an_active_pull_request_has_no_commit() -> None:
    assert forge(RestHost(active())).merge_commit(REPO, 162) is None
