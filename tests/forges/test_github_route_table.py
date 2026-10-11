"""The two fake GitHub hosts answer from one table over one state: the same request
gets the same answer from the in-process host and from the HTTP server, state a test
writes through the server is what the host reads, a scripted route overrides the table
for its test only, and a route no one serves is a recorded 404.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
import pytest

from tests.forges import github_answers as gh
from tests.forges.github_host import GitHubHost, Scripted, answer
from tests.forges.github_routes import API
from tests.forges.github_server import FakeGitHub

BASE = "/repos/example/app"
HEAD = "spec/add-marker/1"
OPEN = {"head": HEAD, "base": "main", "title": "add-marker/1: Register the marker", "body": "b"}
INLINE = ("src/app/marker.py", 3, "name it")

# (id, method, path, query, body): each route the two hosts share, against the state
# `seed` writes: pull request 1 with a review carrying an inline comment, and a comment.
Request = tuple[str, str, str, dict[str, str], Any]
ROUTES: list[Request] = [
    ("pull-list", "GET", f"{BASE}/pulls", {"state": "all"}, None),
    ("pull-find", "GET", f"{BASE}/pulls", {"head": f"example:{HEAD}"}, None),
    ("pull-create", "POST", f"{BASE}/pulls", {}, {**OPEN, "head": "spec/other/1"}),
    ("pull-create-duplicate", "POST", f"{BASE}/pulls", {}, OPEN),
    ("pull-read", "GET", f"{BASE}/pulls/1", {}, None),
    ("pull-update", "PATCH", f"{BASE}/pulls/1", {}, {"base": "develop", "body": "new"}),
    ("pull-close", "PATCH", f"{BASE}/pulls/1", {}, {"state": "closed"}),
    ("review-list", "GET", f"{BASE}/pulls/1/reviews", {}, None),
    ("review-by-id", "GET", f"{BASE}/pulls/1/reviews/1001", {}, None),
    ("review-by-unknown-id", "GET", f"{BASE}/pulls/1/reviews/31337", {}, None),
    ("review-comment-list", "GET", f"{BASE}/pulls/1/comments", {}, None),
    ("reply", "POST", f"{BASE}/pulls/1/comments/5002/replies", {}, {"body": "done"}),
    ("reply-unknown", "POST", f"{BASE}/pulls/1/comments/987654/replies", {}, {"body": "done"}),
    ("comment", "POST", f"{BASE}/issues/1/comments", {}, {"body": "reworked as asked"}),
    ("status", "POST", f"{BASE}/statuses/abc123", {}, {"context": "abk/tier2", "state": "success"}),
    ("label-add", "POST", f"{BASE}/issues/1/labels", {}, {"labels": ["running"]}),
    ("label-list", "GET", f"{BASE}/issues/1/labels", {}, None),
    ("label-remove", "DELETE", f"{BASE}/issues/1/labels/running", {}, None),
    ("repo-label-list", "GET", f"{BASE}/labels", {}, None),
]

RUN = 123
JOB = 456
PULL_ID = gh.pull(1)["id"]


def draft_mutation(name: str, pull_id: str = PULL_ID) -> dict[str, str]:
    return {"query": f'mutation {{ {name}(input: {{pullRequestId: "{pull_id}"}}) {{ id }} }}'}


# The routes only the table answers, against `seed_chain`: pull requests 1 to 4, a stack
# of 1 and 2, and a run with a failed job and its log.
REMAINING: list[Request] = [
    ("draft-convert", "POST", "/graphql", {}, draft_mutation("convertPullRequestToDraft")),
    ("draft-publish", "POST", "/graphql", {}, draft_mutation("markPullRequestReadyForReview")),
    (
        "draft-unknown-pull",
        "POST",
        "/graphql",
        {},
        draft_mutation("convertPullRequestToDraft", "PR_none"),
    ),
    ("stack-find", "GET", f"{BASE}/stacks", {"pull_request": "1"}, None),
    ("stack-find-none", "GET", f"{BASE}/stacks", {"pull_request": "3"}, None),
    ("stack-create", "POST", f"{BASE}/stacks", {}, {"pull_requests": [3, 4]}),
    ("stack-add", "POST", f"{BASE}/stacks/1/add", {}, {"pull_requests": [3]}),
    ("stack-add-unknown", "POST", f"{BASE}/stacks/99/add", {}, {"pull_requests": [3]}),
    ("branch-protection", "GET", f"{BASE}/branches/main/protection", {}, None),
    ("check-rerun", "POST", f"{BASE}/actions/runs/{RUN}/rerun-failed-jobs", {}, {}),
    ("job-list", "GET", f"{BASE}/actions/runs/{RUN}/jobs", {}, None),
    ("job-list-unknown-run", "GET", f"{BASE}/actions/runs/7/jobs", {}, None),
    ("job-log", "GET", f"{BASE}/actions/jobs/{JOB}/logs", {}, None),
    ("job-log-unknown", "GET", f"{BASE}/actions/jobs/9/logs", {}, None),
]

BY_ID = {r[0]: r for r in ROUTES}


def seed(server: FakeGitHub) -> None:
    """Pull request 1, a review with an inline comment on it, and a conversation comment."""
    headers = {"authorization": f"Bearer {server.token}"}
    httpx.post(f"{server.url}{BASE}/pulls", json=OPEN, headers=headers).raise_for_status()
    server.add_review(1, "COMMENTED", "please rename", inline=INLINE)
    server.add_comment(1, "a note")


def seed_chain(server: FakeGitHub) -> None:
    """Pull requests 1 to 4, a stack of 1 and 2, and a run with a failed job and its log."""
    headers = {"authorization": f"Bearer {server.token}"}
    for number in range(1, 5):
        sent = {**OPEN, "head": f"spec/add-marker/{number}"}
        httpx.post(f"{server.url}{BASE}/pulls", json=sent, headers=headers).raise_for_status()
    httpx.post(
        f"{server.url}{BASE}/stacks", json={"pull_requests": [1, 2]}, headers=headers
    ).raise_for_status()
    server.state.jobs[RUN] = [gh.job(JOB, "pre-commit", "failure", RUN)]
    server.state.job_logs[JOB] = gh.JOB_LOG


def _said(reply: httpx.Response) -> Any:
    """The JSON body, or where a redirect points when there is no body."""
    return reply.json() if reply.content else reply.headers.get("location")


def through_server(server: FakeGitHub, request: Request) -> tuple[int, Any]:
    _, method, path, query, body = request
    headers = {"authorization": f"Bearer {server.token}"}
    reply = httpx.request(method, f"{server.url}{path}", params=query, json=body, headers=headers)
    return reply.status_code, _said(reply)


def through_host(host: GitHubHost, request: Request) -> tuple[int, Any]:
    _, method, path, query, body = request
    with httpx.Client(transport=host, base_url=API) as http:
        reply = http.request(method, path, params=query, json=body)
    return reply.status_code, _said(reply)


def alike(request_: Request, seeder: Callable[[FakeGitHub], None]) -> None:
    with FakeGitHub() as for_server, FakeGitHub() as for_host:
        seeder(for_server)
        seeder(for_host)
        host = GitHubHost(state=for_host.state)

        from_host = through_host(host, request_)
        from_server = through_server(for_server, request_)

    assert from_host == from_server
    assert host.unrouted == []
    assert for_server.unrouted() == []


@pytest.mark.parametrize("request_", ROUTES, ids=[r[0] for r in ROUTES])
def test_the_host_and_the_server_answer_a_route_alike_from_the_same_state(
    request_: Request,
) -> None:
    alike(request_, seed)


@pytest.mark.parametrize("request_", REMAINING, ids=[r[0] for r in REMAINING])
def test_the_host_and_the_server_answer_the_remaining_routes_alike_from_the_same_state(
    request_: Request,
) -> None:
    alike(request_, seed_chain)


def test_a_review_with_an_inline_comment_written_through_the_server_is_seen_by_the_host() -> None:
    with FakeGitHub() as server:
        seed(server)
        comment = server.add_review(1, "CHANGES_REQUESTED", "needs a test", inline=INLINE)
        host = GitHubHost(state=server.state)

        reviews = through_host(host, BY_ID["review-list"])[1]
        inline = through_host(host, BY_ID["review-comment-list"])[1]
        listed = through_host(host, BY_ID["pull-list"])[1]

    assert [r["state"] for r in reviews] == ["COMMENTED", "CHANGES_REQUESTED"]
    assert [(c["id"], c["path"], c["line"], c["body"]) for c in inline][-1] == (
        comment,
        "src/app/marker.py",
        3,
        "name it",
    )
    assert [p["number"] for p in listed] == [1]
    assert host.unrouted == []


def test_state_the_host_writes_is_read_back_by_the_server() -> None:
    with FakeGitHub() as server:
        seed(server)
        host = GitHubHost(state=server.state)

        through_host(host, BY_ID["reply"])
        replies = through_server(server, BY_ID["review-comment-list"])[1]

    assert [c["body"] for c in replies if c.get("in_reply_to_id")] == ["done"]


def test_a_scripted_route_overrides_the_table_for_its_test_only() -> None:
    scripted: dict[tuple[str, str], Scripted | list[Scripted]] = {
        ("GET", f"{BASE}/pulls"): answer([{"number": 99}])
    }
    with FakeGitHub() as server:
        seed(server)
        overridden = GitHubHost(state=server.state, routes=scripted)
        plain = GitHubHost(state=server.state)

        said = through_host(overridden, BY_ID["pull-list"])
        table = through_host(plain, BY_ID["pull-list"])
        elsewhere = through_host(overridden, BY_ID["pull-read"])

    assert said == (200, [{"number": 99}])
    assert [p["number"] for p in table[1]] == [1]
    assert elsewhere[0] == 200
    assert plain.unrouted == []


def test_a_route_no_handler_serves_is_a_404_recorded_as_unrouted_by_both_hosts() -> None:
    fork: Request = ("fork", "POST", f"{BASE}/forks", {}, {})
    with FakeGitHub() as server:
        seed(server)
        host = GitHubHost(state=server.state)

        from_host = through_host(host, fork)
        from_server = through_server(server, fork)

    assert from_host[0] == from_server[0] == 404
    assert [(s.method, s.path) for s in host.unrouted] == [("POST", f"{BASE}/forks")]
    assert server.unrouted() == [("POST", f"{BASE}/forks")]


SEEDED: list[Request] = [
    ("pull-update", "PATCH", f"{BASE}/pulls/16", {}, {"base": "develop"}),
    ("review-list", "GET", f"{BASE}/pulls/16/reviews", {}, None),
    ("review-by-id", "GET", f"{BASE}/pulls/16/reviews/1001", {}, None),
    ("review-comment-list", "GET", f"{BASE}/pulls/16/comments", {}, None),
    ("reply", "POST", f"{BASE}/pulls/16/comments/5001/replies", {}, {"body": "done"}),
    ("files", "GET", f"{BASE}/pulls/16/files", {}, None),
    ("comment", "POST", f"{BASE}/issues/16/comments", {}, {"body": "note"}),
]


@pytest.mark.parametrize("request_", SEEDED, ids=[r[0] for r in SEEDED])
def test_a_seeded_pull_request_on_a_pull_scoped_route_is_unrouted_not_a_silent_404(
    request_: Request,
) -> None:
    host = GitHubHost(gh.pull(16))
    absent = (request_[0], request_[1], request_[2].replace("/16", "/99"), {}, request_[4])

    seeded = through_host(host, request_)
    missing = through_host(host, absent)

    assert seeded[0] == 404
    assert [s.path for s in host.unrouted] == [request_[2]]
    assert missing[0] == 404


def test_a_scripted_route_overrides_the_table_on_the_server_for_its_test_only() -> None:
    scripted: dict[tuple[str, str], Scripted | list[Scripted]] = {
        ("GET", f"{BASE}/pulls"): answer([{"number": 99}])
    }
    with FakeGitHub(routes=scripted) as overridden, FakeGitHub() as plain:
        seed(overridden)
        seed(plain)

        said = through_server(overridden, BY_ID["pull-list"])
        table = through_server(plain, BY_ID["pull-list"])

    assert said == (200, [{"number": 99}])
    assert [p["number"] for p in table[1]] == [1]


def test_a_host_built_over_a_state_refuses_what_the_state_decides() -> None:
    with FakeGitHub() as server, pytest.raises(ValueError):
        GitHubHost(state=server.state, page_size=5)


def test_a_host_built_over_a_state_refuses_an_explicit_zero_page_size() -> None:
    with FakeGitHub() as server, pytest.raises(ValueError):
        GitHubHost(state=server.state, page_size=0)


def test_a_pull_request_made_on_a_seeded_host_gets_the_next_number_and_a_seeded_head_is_taken() -> (
    None
):
    host = GitHubHost(gh.pull(1, head="spec/a/1"))
    other = {**OPEN, "head": "spec/b/1"}

    made = through_host(host, ("c", "POST", f"{BASE}/pulls", {}, other))
    listed = through_host(host, BY_ID["pull-list"])
    again = through_host(host, ("c", "POST", f"{BASE}/pulls", {}, {**OPEN, "head": "spec/a/1"}))

    assert made[0] == 201
    assert made[1]["number"] == 2
    assert [(p["number"], p["head"]["ref"]) for p in listed[1]] == [
        (1, "spec/a/1"),
        (2, "spec/b/1"),
    ]
    assert again[0] == 422
