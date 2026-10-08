"""The retry layer over the real forges' operations, at the HTTP boundary.

A forge operation that swallows its own failures hides a transient one from the
layer, so these run each such operation through `ResilientForge` over a stand-in
host: the host fails once, and the call is made again."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agent_build_kit.forges.azure_devops import AzureDevOpsForge
from agent_build_kit.forges.base import PullRequest, RepoId
from agent_build_kit.forges.github import GitHubForge
from agent_build_kit.forges.resilient import ResilientForge, RetryPolicy
from agent_build_kit.forges.transport import HostUnavailable
from tests.fake_clock import FakeClock
from tests.forges import azure_answers
from tests.forges import github_answers as gh
from tests.forges.azure_rest_host import RestHost
from tests.forges.azure_rest_host import refusal as azure_refusal
from tests.forges.github_host import GitHubHost, answer, refusal

GITHUB = RepoId(forge="github", account="example", name="app")
AZURE = RepoId(forge="azure_devops", account="acme", project="Some Project", name="Some Repo")
BASE = "/repos/example/app"
STACKS = f"{BASE}/stacks"
ATTEMPTS = 3


def wrap(inner: Any) -> ResilientForge:
    clock = FakeClock()
    return ResilientForge(
        inner,
        RetryPolicy(attempts=ATTEMPTS, deadline_seconds=1000.0),
        clock,
        clock.advance,
    )


def failing(number: int) -> PullRequest:
    return PullRequest(
        number=number, head="spec/x/1", base="main", state="open", failing_checks=("pre-commit",)
    )


class OnceRefused(dict):
    """`RestHost.refuse` whose answers are each given once."""

    def get(self, key: Any, default: Any = None) -> Any:
        return self.pop(key, default)


# --- GitHub ------------------------------------------------------------------------


@pytest.mark.usefixtures("github_env")
class TestGitHub:
    def test_a_status_answered_503_then_201_is_posted_twice_and_succeeds(self) -> None:
        route = ("POST", f"{BASE}/statuses/abc1234def")
        host = GitHubHost(routes={route: [refusal(503, "down"), answer({"id": 1}, 201)]})

        wrap(GitHubForge(http=host)).post_status(
            GITHUB, sha="abc1234def", ok=True, context="c", description="d"
        )

        assert len(host.calls(*route)) == 2

    def test_a_status_that_never_lands_is_contained_not_raised(self) -> None:
        route = ("POST", f"{BASE}/statuses/abc1234def")
        host = GitHubHost(routes={route: refusal(503, "down")})

        wrap(GitHubForge(http=host)).post_status(
            GITHUB, sha="abc1234def", ok=True, context="c", description="d"
        )

        assert len(host.calls(*route)) == ATTEMPTS

    def test_find_pr_answered_503_then_a_hit_returns_the_number(self) -> None:
        route = ("GET", f"{BASE}/pulls")
        host = GitHubHost(routes={route: [refusal(503, "down"), answer([{"number": 11}])]})

        assert wrap(GitHubForge(http=host)).find_pr(GITHUB, head="h") == 11
        assert len(host.calls(*route)) == 2

    def test_find_pr_that_stays_down_is_unavailable_not_no_pull_request(self) -> None:
        host = GitHubHost(routes={("GET", f"{BASE}/pulls"): refusal(503, "down")})

        with pytest.raises(HostUnavailable):
            wrap(GitHubForge(http=host)).find_pr(GITHUB, head="h")

    def test_a_create_that_timed_out_is_confirmed_through_a_find_that_fails_once(self) -> None:
        create = ("POST", f"{BASE}/pulls")
        listing = ("GET", f"{BASE}/pulls")
        host = GitHubHost(
            routes={
                create: [httpx.ReadTimeout("slow"), answer({"number": 9}, 201)],
                listing: [refusal(503, "down"), answer([{"number": 9}])],
            }
        )

        made = wrap(GitHubForge(http=host)).create_pr(
            GITHUB, head="h", base="main", title="t", body="b"
        )

        assert made == 9
        assert len(host.calls(*create)) == 1

    def test_a_stacks_post_answered_502_is_repeated(self) -> None:
        created = {
            "id": 1,
            "number": 4,
            "node_id": "PRS_x",
            "url": "https://api.github.com" + STACKS + "/4",
            "base": {"ref": "main"},
            "open": True,
            "created_at": "2026-09-28T14:02:11Z",
            "pull_requests": [
                {"number": 11, "state": "open", "head": {"ref": "a", "sha": "1" * 40}}
            ],
        }
        host = GitHubHost(
            routes={
                ("POST", STACKS): [refusal(502, "bad gateway"), answer(created, 201)],
                ("GET", STACKS): answer([]),
            }
        )

        stack = wrap(GitHubForge(http=host)).create_stack(GITHUB, [11, 12])

        assert stack.number == 4
        assert len(host.calls("POST", STACKS)) == 2

    def test_a_rerun_answered_503_then_201_is_repeated(self) -> None:
        rollup = [gh.check_run("CI", "CANCELLED", run=123, job=9)]
        route = ("POST", f"{BASE}/actions/runs/123/rerun-failed-jobs")
        host = GitHubHost(
            gh.pull(16, checks=rollup), routes={route: [refusal(503, "down"), answer({}, 201)]}
        )
        pull = PullRequest(number=16, head="h", base="main", state="open")

        wrap(GitHubForge(http=host)).rerun_checks(GITHUB, pull)

        assert len(host.calls(*route)) == 2

    def test_an_update_answered_503_then_200_is_repeated(self) -> None:
        route = ("PATCH", f"{BASE}/pulls/7")
        host = GitHubHost(routes={route: [refusal(503, "down"), answer({"number": 7})]})

        wrap(GitHubForge(http=host)).update_pr(GITHUB, 7, base="main")

        assert len(host.calls(*route)) == 2

    def test_a_branch_delete_answered_503_then_204_is_repeated(self) -> None:
        route = ("DELETE", f"{BASE}/git/refs/heads/b")
        host = GitHubHost(routes={route: [refusal(503, "down"), httpx.Response(204)]})

        wrap(GitHubForge(http=host)).delete_remote_branch(GITHUB, "b")

        assert len(host.calls(*route)) == 2

    def test_a_comment_that_never_lands_returns_no_ids(self) -> None:
        route = ("POST", f"{BASE}/issues/7/comments")
        host = GitHubHost(routes={route: refusal(503, "down")})

        assert wrap(GitHubForge(http=host)).post_comment(GITHUB, 7, body="x") == []

    def test_a_reply_that_never_lands_returns_no_ids(self) -> None:
        route = ("POST", f"{BASE}/pulls/7/comments/5/replies")
        host = GitHubHost(routes={route: refusal(503, "down")})

        assert wrap(GitHubForge(http=host)).post_reply(GITHUB, 7, note_id="5", body="x") == []

    def test_a_merge_guard_answered_503_then_protected_is_repeated(self) -> None:
        route = ("GET", f"{BASE}/branches/main/protection")
        host = GitHubHost(
            routes={route: [refusal(503, "down"), answer({"required_status_checks": {}})]}
        )

        assert wrap(GitHubForge(http=host)).merge_guard(GITHUB, branch="main") == ""
        assert len(host.calls(*route)) == 2

    def test_a_jobs_listing_answered_503_then_a_failed_job_returns_the_log(self) -> None:
        run, job = 36892939541, 110472774948
        route = ("GET", f"{BASE}/actions/runs/{run}/jobs")
        listing = {"total_count": 1, "jobs": [gh.job(job, "pre-commit", "failure", run)]}
        host = GitHubHost(
            gh.pull(50, checks=[gh.check_run("pre-commit", "FAILURE", run=run, job=job)]),
            routes={route: [refusal(503, "down"), answer(listing)]},
            job_logs={job: gh.JOB_LOG},
        )

        text = wrap(GitHubForge(http=host)).failed_check_logs(GITHUB, failing(50))

        assert "pre-commit" in text
        assert "could not be fetched" not in text
        assert len(host.calls(*route)) == 2

    def test_a_jobs_listing_that_stays_down_returns_an_empty_string_not_a_raise(self) -> None:
        run, job = 36892939541, 110472774948
        route = ("GET", f"{BASE}/actions/runs/{run}/jobs")
        host = GitHubHost(
            gh.pull(50, checks=[gh.check_run("pre-commit", "FAILURE", run=run, job=job)]),
            routes={route: refusal(503, "down")},
        )

        text = wrap(GitHubForge(http=host)).failed_check_logs(GITHUB, failing(50))

        assert text == ""
        assert len(host.calls(*route)) == ATTEMPTS


# --- Azure DevOps ------------------------------------------------------------------


@pytest.mark.usefixtures("rest_env")
class TestAzureDevOps:
    def test_a_pull_request_status_answered_503_then_200_is_posted_twice(self) -> None:
        route = ("POST", "pullrequests/162/statuses")
        host = RestHost(azure_answers.OPEN, refuse=OnceRefused({route: azure_refusal(503, "down")}))

        wrap(AzureDevOpsForge(http=host)).post_status(
            AZURE,
            sha="abc123",
            ok=True,
            context="local/tier2",
            description="d",
            head="spec/add-marker/1",
        )

        assert len(host.calls(*route)) == 2

    def test_an_access_check_answered_503_then_200_is_repeated(self) -> None:
        route = ("GET", "")
        host = RestHost(azure_answers.OPEN, refuse=OnceRefused({route: azure_refusal(503, "down")}))

        assert wrap(AzureDevOpsForge(http=host)).check_access(AZURE) == ""
