"""GitHub at the HTTP boundary: a stand-in answering the REST and GraphQL calls.

What it receives is the request the forge's client sends (method, path, query,
headers, JSON body); what it sends back is the raw body GitHub sends. What it
does that a canned answer cannot:

- answers `POST /graphql` by what the query asks for: the listing of a
  repository's pull requests a hundred (or `page_size`) a page, saying where the
  next page starts in `pageInfo`, and finding the page by the cursor the request
  carries, whether as a variable or written into the query; one pull request by
  number; and the two draft mutations, which change what the next read says;
- answers the REST routes for pull requests, reviews, inline comments, issue
  comments, commit statuses and labels from the table in `github_routes.py`, over a
  `GitHubState` that `FakeGitHub` shares through `state=`: a route is added there, once,
  for both hosts, and a pull request is derived from that state when it is read;
- pages the lists it is given (`paged`) by `page` and `per_page`, never more than
  `page_size` a page, with the `Link` header GitHub sends;
- lists a run's jobs, and answers a job's log with the redirect to storage that
  GitHub sends, the storage host answering the text;
- keeps every request, and every request it had no answer for.

A scripted route comes first and overrides the table for its test only. Everything
else is scripted, by `(method, path)`: a response, a list of them
answered in turn (the last repeats), an exception, or a function of the request.
A route nobody scripted is answered 404 and recorded in `unrouted`, which the
tests' fixture asserts is empty: a forge reaching for a resource nobody expected
is the thing under test.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import httpx

from tests.forges import github_answers
from tests.forges.github_routes import (
    GitHubState,
    Seen,
    answer,
    page,
    refusal,
    serve,
)

STORAGE = "https://productionresultssa0.blob.core.windows.net"

# Every host built in a test, so its fixture can say what nothing answered.
HOSTS: list[GitHubHost] = []

Scripted = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


class GitHubHost(httpx.MockTransport):
    def __init__(
        self,
        *pulls: dict,
        routes: dict[tuple[str, str], Scripted | list[Scripted]] | None = None,
        paged: dict[str, list] | None = None,
        repo_labels: list[tuple[str, str, str]] | None = None,
        pr_labels: dict[int, list[str]] | None = None,
        jobs: dict[int, list[dict]] | None = None,
        job_logs: dict[int, str] | None = None,
        page_size: int | None = None,
        draft_refusal: str = "",
        state: GitHubState | None = None,
    ) -> None:
        if state is None:
            state = GitHubState(
                *pulls, page_size=page_size or 100, repo_labels=repo_labels, pr_labels=pr_labels
            )
        elif pulls or repo_labels or pr_labels or page_size:
            raise ValueError(
                "a host built over a state takes its pull requests, labels and page size from it"
            )
        self.state = state
        self.pulls = state.pulls
        self.repo_labels = state.repo_labels
        self.pr_labels = state.pr_labels
        self.routes = {k: v if isinstance(v, list) else [v] for k, v in (routes or {}).items()}
        self.paged = paged or {}
        self.jobs = jobs or {}
        self.job_logs = job_logs or {}
        self.page_size = state.page_size
        self.draft_refusal = draft_refusal
        self.seen: list[Seen] = []
        self.unrouted: list[Seen] = []
        self._answered: dict[tuple[str, str], int] = {}
        HOSTS.append(self)
        super().__init__(self._handle)

    # --- what a test asks ---------------------------------------------------------

    def calls(self, method: str | None = None, path: str | None = None) -> list[Seen]:
        return [
            s
            for s in self.seen
            if (method is None or s.method == method) and (path is None or s.path == path)
        ]

    def graphql(self, containing: str = "") -> list[Seen]:
        return [s for s in self.seen if s.path == "/graphql" and containing in s.query]

    def pull(self, number: int) -> dict:
        return self.state.pull(number)

    # --- routing ------------------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        seen = Seen(request)
        self.seen.append(seen)
        if seen.host == urlhost(STORAGE):
            return self._storage(seen)
        key = (seen.method, seen.path)
        if key in self.routes:
            return self._scripted(key, request)
        if seen.method == "GET" and seen.path in self.paged:
            return page(seen, self.paged[seen.path], self.page_size)
        for found in (self._graphql(seen), serve(self.state, seen), self._actions(seen)):
            if found is not None:
                return found
        self.unrouted.append(seen)
        return refusal(404, "Not Found")

    def _scripted(self, key: tuple[str, str], request: httpx.Request) -> httpx.Response:
        replies = self.routes[key]
        turn = self._answered.get(key, 0)
        self._answered[key] = turn + 1
        reply = replies[min(turn, len(replies) - 1)]
        if isinstance(reply, Exception):
            raise reply
        return reply(request) if callable(reply) else reply

    # --- GraphQL ------------------------------------------------------------------

    def _graphql(self, seen: Seen) -> httpx.Response | None:
        if seen.method != "POST" or seen.path != "/graphql":
            return None
        text = json.dumps(seen.body)
        for mutation, draft in (
            ("convertPullRequestToDraft", True),
            ("markPullRequestReadyForReview", False),
        ):
            if mutation in seen.query:
                return self._mutate(mutation, draft, text)
        if re.search(r"\bpullRequests\s*\(", seen.query):
            return self._listing(text)
        if re.search(r"\bpullRequest\s*\(", seen.query):
            return self._one(seen)
        return None

    def _listing(self, text: str) -> httpx.Response:
        nodes = self.state.nodes()
        start = 0
        for index in range(0, len(nodes), self.page_size):
            if re.search(rf"cursor:{index}(?!\d)", text):
                start = index
        end = start + self.page_size
        more = end < len(nodes)
        connection = {
            "totalCount": len(nodes),
            "pageInfo": {
                "hasNextPage": more,
                "hasPreviousPage": start > 0,
                "startCursor": f"cursor:{start}",
                "endCursor": f"cursor:{end}" if more else f"cursor:{start}-end",
            },
            "nodes": nodes[start:end],
        }
        return answer({"data": {"repository": {"pullRequests": connection}}})

    def _one(self, seen: Seen) -> httpx.Response:
        variables = (seen.body or {}).get("variables") or {}
        numbers = [v for v in variables.values() if isinstance(v, int)]
        numbers += [int(n) for n in re.findall(r"number:\s*(\d+)", seen.query)]
        node = next((p for p in self.state.nodes() if p["number"] in numbers), None)
        return answer({"data": {"repository": {"pullRequest": node}}})

    def _mutate(self, mutation: str, draft: bool, text: str) -> httpx.Response:
        if self.draft_refusal:
            error = {"type": "UNPROCESSABLE", "message": self.draft_refusal}
            return answer({"data": {mutation: None}, "errors": [error]})
        node = next((p for p in self.pulls if p["id"] in text), None)
        if node is None:
            return answer({"data": {mutation: None}, "errors": [{"message": "Could not resolve"}]})
        node["isDraft"] = draft
        payload = {"pullRequest": {"id": node["id"], "isDraft": draft}}
        return answer({"data": {mutation: payload}})

    # --- Actions ------------------------------------------------------------------

    def _actions(self, seen: Seen) -> httpx.Response | None:
        listed = re.fullmatch(r"/repos/[^/]+/[^/]+/actions/runs/(\d+)/jobs", seen.path)
        if listed and seen.method == "GET":
            jobs = self.jobs.get(int(listed[1]), [])
            return answer({"total_count": len(jobs), "jobs": jobs})
        log = re.fullmatch(r"/repos/[^/]+/[^/]+/actions/jobs/(\d+)/logs", seen.path)
        if log and seen.method == "GET":
            if int(log[1]) not in self.job_logs:
                return refusal(404, "Not Found")
            location = f"{STORAGE}/actions-results/{log[1]}.log?sig=abc"
            return httpx.Response(302, headers={"location": location})
        return None

    def _storage(self, seen: Seen) -> httpx.Response:
        job = int(re.search(r"/(\d+)\.log", seen.path)[1])  # type: ignore[index]
        text = self.job_logs[job]
        return httpx.Response(200, content=text, headers={"content-type": "text/plain"})


def urlhost(url: str) -> str:
    return httpx.URL(url).host


def listing_of(count: int, **overrides: Any) -> list[dict]:
    """`count` open pull requests numbered from 1, in listing order."""
    return [github_answers.pull(n, **overrides) for n in range(1, count + 1)]
