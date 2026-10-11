"""GitHub at the HTTP boundary: a stand-in answering the REST and GraphQL calls.

What it receives is the request the forge's client sends (method, path, query,
headers, JSON body); what it sends back is the raw body GitHub sends. What it
does that a canned answer cannot:

- answers every GitHub route from the table in `github_routes.py`, over a
  `GitHubState` that `FakeGitHub` shares through `state=`: a route is added there, once,
  for both hosts, and a pull request is derived from that state when it is read. That
  includes `POST /graphql` (the listing a hundred, or `page_size`, a page, finding the
  page by the cursor the request carries; one pull request by number; the two draft
  mutations), the REST routes for pull requests, reviews, inline comments, issue
  comments, commit statuses, labels and stacks, branch protection, a run's jobs and a
  job's log with the redirect to storage that GitHub sends;
- answers the storage host's log text;
- pages the lists it is given (`paged`) by `page` and `per_page`, never more than
  `page_size` a page, with the `Link` header GitHub sends;
- keeps every request, and every request it had no answer for.

A scripted route comes first and overrides the table for its test only. Everything
else is scripted, by `(method, path)`: a response, a list of them
answered in turn (the last repeats), an exception, or a function of the request.
A route nobody scripted is answered 404 and recorded in `unrouted`, which the
tests' fixture asserts is empty: a forge reaching for a resource nobody expected
is the thing under test.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import httpx

from tests.forges import github_answers
from tests.forges.github_routes import (
    GRAPHQL,
    STORAGE,
    GitHubState,
    Seen,
    page,
    refusal,
    serve,
)
from tests.forges.github_routes import (
    answer as answer,
)

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
                *pulls,
                page_size=100 if page_size is None else page_size,
                repo_labels=repo_labels,
                pr_labels=pr_labels,
            )
        elif pulls or repo_labels or pr_labels or page_size is not None:
            raise ValueError(
                "a host built over a state takes its pull requests, labels and page size from it"
            )
        state.jobs.update(jobs or {})
        state.job_logs.update(job_logs or {})
        if draft_refusal:
            state.draft_refusal = draft_refusal
        self.state = state
        self.pulls = state.pulls
        self.repo_labels = state.repo_labels
        self.pr_labels = state.pr_labels
        self.routes = {k: v if isinstance(v, list) else [v] for k, v in (routes or {}).items()}
        self.paged = paged or {}
        self.page_size = state.page_size
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
        return [s for s in self.seen if s.path == GRAPHQL and containing in s.query]

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
        found = serve(self.state, seen)
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

    def _storage(self, seen: Seen) -> httpx.Response:
        job = int(re.search(r"/(\d+)\.log", seen.path)[1])  # type: ignore[index]
        text = self.state.job_logs[job]
        return httpx.Response(200, content=text, headers={"content-type": "text/plain"})


def urlhost(url: str) -> str:
    return httpx.URL(url).host


def listing_of(count: int, **overrides: Any) -> list[dict]:
    """`count` open pull requests numbered from 1, in listing order."""
    return [github_answers.pull(n, **overrides) for n in range(1, count + 1)]
