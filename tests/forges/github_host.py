"""GitHub at the HTTP boundary: a stand-in answering the REST and GraphQL calls.

What it receives is the request the forge's client sends (method, path, query,
headers, JSON body); what it sends back is the raw body GitHub sends. What it
does that a canned answer cannot:

- answers `POST /graphql` by what the query asks for: the listing of a
  repository's pull requests a hundred (or `page_size`) a page, saying where the
  next page starts in `pageInfo`, and finding the page by the cursor the request
  carries, whether as a variable or written into the query; one pull request by
  number; and the two draft mutations, which change what the next read says;
- keeps repository labels and each pull request's labels, matches names without
  regard to case as GitHub does, and answers adding an unknown label to a pull
  request by creating it in the default colour, as GitHub does;
- pages the lists it is given (`paged`) by `page` and `per_page`, never more than
  `page_size` a page, with the `Link` header GitHub sends;
- lists a run's jobs, and answers a job's log with the redirect to storage that
  GitHub sends, the storage host answering the text;
- keeps every request, and every request it had no answer for.

Everything else is scripted, by `(method, path)`: a response, a list of them
answered in turn (the last repeats), an exception, or a function of the request.
A route nobody scripted is answered 404 and recorded in `unrouted`, which the
tests' fixture asserts is empty: a forge reaching for a resource nobody expected
is the thing under test.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any

import httpx

from tests.forges import github_answers
from tests.forges.github_routes import GitHubState

API = "https://api.github.com"
STORAGE = "https://productionresultssa0.blob.core.windows.net"
JSON = {"content-type": "application/json; charset=utf-8"}
DEFAULT_COLOUR = "ededed"

# Every host built in a test, so its fixture can say what nothing answered.
HOSTS: list[GitHubHost] = []

Scripted = httpx.Response | Exception | Callable[[httpx.Request], httpx.Response]


def answer(
    body: object, status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body), headers={**JSON, **(headers or {})})


def refusal(status: int, message: str, errors: list[dict] | None = None) -> httpx.Response:
    """An error as the REST API sends one."""
    body: dict[str, Any] = {
        "message": message,
        "documentation_url": "https://docs.example.test/rest",
        "status": str(status),
    }
    if errors is not None:
        body["errors"] = errors
    return answer(body, status)


class Seen:
    """One request that reached the host, normalised for assertions."""

    def __init__(self, request: httpx.Request) -> None:
        self.request = request
        self.method = request.method
        self.path = request.url.path
        self.host = request.url.host
        self.params = dict(request.url.params)
        self.headers = request.headers
        self.body: Any = json.loads(request.content) if request.content else None

    @property
    def query(self) -> str:
        """The GraphQL document of a `/graphql` call."""
        return str((self.body or {}).get("query", ""))

    def __repr__(self) -> str:
        return f"{self.method} {self.path} {self.params} {self.body}"


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
        page_size: int = 100,
        draft_refusal: str = "",
        state: GitHubState | None = None,
    ) -> None:
        self.pulls = [deepcopy(p) for p in pulls]
        self.routes = {k: v if isinstance(v, list) else [v] for k, v in (routes or {}).items()}
        self.paged = paged or {}
        self.repo_labels: dict[str, dict] = {}
        for name, colour, description in repo_labels or []:
            self.repo_labels[name] = self._label(name, colour, description)
        self.pr_labels: dict[int, list[str]] = {n: list(v) for n, v in (pr_labels or {}).items()}
        self.jobs = jobs or {}
        self.job_logs = job_logs or {}
        self.page_size = page_size
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
        return next(p for p in self.pulls if p["number"] == number)

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
            return self._page(seen, self.paged[seen.path])
        for handler in (self._graphql, self._labels, self._actions, self._pulls):
            found = handler(seen)
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

    def _page(self, seen: Seen, items: list) -> httpx.Response:
        size = min(int(seen.params.get("per_page", 30)), self.page_size)
        page = int(seen.params.get("page", 1))
        chunk = items[(page - 1) * size : page * size]
        headers = {}
        if page * size < len(items):
            query = {**seen.params, "page": str(page + 1)}
            link = httpx.URL(f"{API}{seen.path}", params=query)
            headers["link"] = f'<{link}>; rel="next"'
        return answer(chunk, headers=headers)

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
        start = 0
        for index in range(0, len(self.pulls), self.page_size):
            if re.search(rf"cursor:{index}(?!\d)", text):
                start = index
        end = start + self.page_size
        nodes = self.pulls[start:end]
        more = end < len(self.pulls)
        connection = {
            "totalCount": len(self.pulls),
            "pageInfo": {
                "hasNextPage": more,
                "hasPreviousPage": start > 0,
                "startCursor": f"cursor:{start}",
                "endCursor": f"cursor:{end}" if more else f"cursor:{start}-end",
            },
            "nodes": nodes,
        }
        return answer({"data": {"repository": {"pullRequests": connection}}})

    def _one(self, seen: Seen) -> httpx.Response:
        variables = (seen.body or {}).get("variables") or {}
        numbers = [v for v in variables.values() if isinstance(v, int)]
        numbers += [int(n) for n in re.findall(r"number:\s*(\d+)", seen.query)]
        node = next((p for p in self.pulls if p["number"] in numbers), None)
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

    # --- pull requests by REST ----------------------------------------------------

    def _pulls(self, seen: Seen) -> httpx.Response | None:
        found = re.fullmatch(r"/repos/[^/]+/[^/]+/pulls/(\d+)", seen.path)
        if not found or seen.method != "GET":
            return None
        number = int(found[1])
        node = next((p for p in self.pulls if p["number"] == number), None)
        if node is None:
            return refusal(404, "Not Found")
        return answer({"number": number, "node_id": node["id"], "draft": node["isDraft"]})

    # --- labels -------------------------------------------------------------------

    @staticmethod
    def _label(name: str, colour: str, description: str | None) -> dict:
        return {
            "id": abs(hash(name)) % 10**9,
            "node_id": "LA_kwDOAAAAAc8AAAABAAAAAQ",
            "name": name,
            "color": colour,
            "default": False,
            "description": description,
        }

    def _repo_label(self, name: str) -> str | None:
        return next((n for n in self.repo_labels if n.casefold() == name.casefold()), None)

    def _labels(self, seen: Seen) -> httpx.Response | None:
        repo = re.fullmatch(r"/repos/[^/]+/[^/]+/labels(?:/(?P<name>.+))?", seen.path)
        issue = re.fullmatch(
            r"/repos/[^/]+/[^/]+/issues/(?P<n>\d+)/labels(?:/(?P<name>.+))?", seen.path
        )
        if repo:
            return self._repo_labels(seen, repo["name"])
        if issue:
            return self._issue_labels(seen, int(issue["n"]), issue["name"])
        return None

    def _repo_labels(self, seen: Seen, name: str | None) -> httpx.Response:
        body = seen.body or {}
        if name is None and seen.method == "GET":
            return self._page(seen, list(self.repo_labels.values()))
        if name is None and seen.method == "POST":
            if self._repo_label(body["name"]):
                error = [{"resource": "Label", "code": "already_exists", "field": "name"}]
                return refusal(422, "Validation Failed", error)
            made = self._label(
                body["name"], body.get("color", DEFAULT_COLOUR), body.get("description")
            )
            self.repo_labels[body["name"]] = made
            return answer(made, 201)
        if name is None:
            return refusal(405, "Method Not Allowed")
        held = self._repo_label(name)
        if held is None:
            return refusal(404, "Not Found")
        if seen.method == "GET":
            return answer(self.repo_labels[held])
        if seen.method == "PATCH":
            label = self.repo_labels.pop(held)
            label.update({k: v for k, v in body.items() if k in ("color", "description")})
            label["name"] = body.get("new_name", held)
            self.repo_labels[label["name"]] = label
            return answer(label)
        return refusal(405, "Method Not Allowed")

    def _issue_labels(self, seen: Seen, number: int, name: str | None) -> httpx.Response:
        names = self.pr_labels.setdefault(number, [])
        body = seen.body
        if seen.method == "GET" and name is None:
            return answer([self.repo_labels[n] for n in names if n in self.repo_labels])
        if seen.method in ("POST", "PUT") and name is None:
            asked = body.get("labels", []) if isinstance(body, dict) else body
            asked = [a["name"] if isinstance(a, dict) else a for a in asked]
            if seen.method == "PUT":
                names.clear()
            for label in asked:
                held = self._repo_label(label)
                if held is None:  # GitHub creates it, in its own colour
                    self.repo_labels[label] = self._label(label, DEFAULT_COLOUR, None)
                    held = label
                if held not in names:
                    names.append(held)
            return answer([self.repo_labels[n] for n in names])
        if seen.method == "DELETE" and name is None:
            names.clear()
            return answer([])
        if seen.method == "DELETE" and name:
            held = next((n for n in names if n.casefold() == name.casefold()), None)
            if held is None:
                return refusal(404, "Label does not exist")
            names.remove(held)
            return answer([self.repo_labels[n] for n in names if n in self.repo_labels])
        return refusal(405, "Method Not Allowed")

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
