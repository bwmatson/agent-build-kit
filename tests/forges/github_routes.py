"""The one table of fake GitHub routes, and the one state they answer from.

A route is a method, a path pattern and a handler over `GitHubState`. The in-process
host (`github_host.GitHubHost`) and the HTTP server (`github_server.FakeGitHub`) both
look a request up in a scripted override first and then here (`serve`); a request no
handler serves is the host's 404, recorded as unrouted.

The state holds the pull requests, their reviews and inline comments, the labels, the
commit statuses and the counters that give things ids. The pull request node a
listing returns is derived from it when it is read (`GitHubState.nodes`), so a write
by a test is seen by the next read of either host with nothing to keep in step.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from copy import deepcopy
from typing import Any, NamedTuple

import httpx

from tests.forges import github_answers

API = "https://api.github.com"
JSON = {"content-type": "application/json; charset=utf-8"}
DEFAULT_COLOUR = "ededed"

_MERGED_AT = "2026-10-01T12:00:00Z"
_DECIDING = ("APPROVED", "CHANGES_REQUESTED")
_REVIEWER = {"login": "reviewer", "id": 4242, "type": "User", "site_admin": False}
_COMMIT = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"
_REPO = r"/repos/[^/]+/[^/]+"


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
    """One request that reached a host, normalised for assertions."""

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


def page(seen: Seen, items: list, size: int) -> httpx.Response:
    """One page of `items` by `page` and `per_page`, never more than `size`, with the
    `Link` header GitHub sends."""
    size = min(int(seen.params.get("per_page", 30)), size)
    number = int(seen.params.get("page", 1))
    chunk = items[(number - 1) * size : number * size]
    headers = {}
    if number * size < len(items):
        query = {**seen.params, "page": str(number + 1)}
        link = httpx.URL(f"{API}{seen.path}", params=query)
        headers["link"] = f'<{link}>; rel="next"'
    return answer(chunk, headers=headers)


class Pull:
    """What the forge and the test have done to one pull request."""

    def __init__(
        self, number: int, owner: str, head: str, base: str, title: str, body: str
    ) -> None:
        self.number = number
        self.owner = owner
        self.head = head
        self.base = base
        self.title = title
        self.body = body
        self.merged = False
        self.closed = False
        self.comments: list[tuple[str, str]] = []
        # As the REST API lists them: a review has its own numeric id, an inline
        # comment another, and a reply is an inline comment naming its parent.
        self.reviews: list[dict[str, Any]] = []
        self.inline: list[dict[str, Any]] = []

    def decision(self) -> str | None:
        decided = [r["state"] for r in self.reviews if r["state"] in _DECIDING]
        return decided[-1] if decided else None


def make_label(name: str, colour: str, description: str | None) -> dict:
    return {
        "id": abs(hash(name)) % 10**9,
        "node_id": "LA_kwDOAAAAAc8AAAABAAAAAQ",
        "name": name,
        "color": colour,
        "default": False,
        "description": description,
    }


class GitHubState:
    """Everything the routes answer from, for one repository such as `example/app`:
    pull requests are kept by number alone, whatever repository the path names."""

    def __init__(
        self,
        *pulls: dict,
        first_number: int = 1,
        page_size: int = 100,
        repo_labels: list[tuple[str, str, str]] | None = None,
        pr_labels: dict[int, list[str]] | None = None,
    ) -> None:
        # The stored nodes: what a host was seeded with, and what the draft mutations
        # change. A pull request made through the routes also has a `Pull` in `made`,
        # and is read through `nodes`.
        self.pulls = [deepcopy(p) for p in pulls]
        self.made: dict[int, Pull] = {}
        self.page_size = page_size
        self.next_number = first_number
        self.ids = 0
        self.statuses: list[tuple[str, str, str]] = []
        self.repo_labels: dict[str, dict] = {
            name: make_label(name, colour, description)
            for name, colour, description in repo_labels or []
        }
        self.pr_labels: dict[int, list[str]] = {n: list(v) for n, v in (pr_labels or {}).items()}

    # --- reading ------------------------------------------------------------------

    def pull(self, number: int) -> dict:
        """A pull request as the listing query answers it."""
        return self._node(self.stored(number))

    def stored(self, number: int) -> dict:
        """The node a pull request was seeded or made with, which the draft mutations change."""
        return next(p for p in self.pulls if p["number"] == number)

    def seeded(self, number: int) -> bool:
        """Whether a pull request exists that no route made, so has no `Pull`."""
        return number not in self.made and any(p["number"] == number for p in self.pulls)

    def nodes(self) -> list[dict]:
        """Every pull request as the listing query answers it, derived from the state."""
        return [self._node(p) for p in self.pulls]

    def _node(self, stored: dict) -> dict:
        made = self.made.get(stored["number"])
        if made is None:
            return stored
        node = github_answers.pull(
            made.number,
            head=made.head,
            base=made.base,
            state="MERGED" if made.merged else "CLOSED" if made.closed else "OPEN",
            draft=stored["isDraft"],
            merged_at=_MERGED_AT if made.merged else None,
            review_decision=made.decision(),
            labels=tuple(self.pr_labels.get(made.number, ())),
            comments=tuple(made.comments),
            reviews=tuple((r["node_id"], r["state"], r["body"]) for r in made.reviews),
        )
        node["title"] = made.title
        return node

    def document(self, node: dict) -> dict[str, Any]:
        """A pull request as the REST API answers it."""
        made = self.made.get(node["number"])
        owner = made.owner if made else github_answers.OWNER
        return {
            "number": node["number"],
            "node_id": node["id"],
            "state": "open" if node["state"] == "OPEN" else "closed",
            "draft": node["isDraft"],
            "title": node["title"],
            "body": made.body if made else "",
            "merged": node["state"] == "MERGED",
            "head": {"ref": node["headRefName"], "label": f"{owner}:{node['headRefName']}"},
            "base": {"ref": node["baseRefName"]},
            "html_url": node["url"],
        }

    def repo_label(self, name: str) -> str | None:
        return next((n for n in self.repo_labels if n.casefold() == name.casefold()), None)

    # --- writing ------------------------------------------------------------------

    def new_pull(self, owner: str, body: dict[str, Any]) -> Pull:
        head, base = str(body.get("head", "")), str(body.get("base", "main"))
        number = self.next_number
        self.next_number += 1
        made = Pull(
            number, owner, head, base, str(body.get("title", "")), str(body.get("body", ""))
        )
        self.made[number] = made
        self.pulls.append(github_answers.pull(number, head=head, base=base))
        return made

    def new_comment(self, pull: Pull, body: str) -> str:
        self.ids += 1
        node = f"IC_kwDOAAAAAc{self.ids:08d}"
        pull.comments.append((node, body))
        return node

    def new_review(self, pull: Pull, state: str, body: str) -> dict[str, Any]:
        self.ids += 1
        review_id = 1000 + self.ids
        review = {
            "id": review_id,
            "node_id": f"PRR_kwDOAAAAAc{self.ids:08d}",
            "user": _REVIEWER,
            "body": body,
            "state": state,
            "html_url": f"{github_answers.WEB}/pull/{pull.number}#pullrequestreview-{review_id}",
            "submitted_at": "2026-09-28T10:00:00Z",
            "commit_id": _COMMIT,
            "author_association": "CONTRIBUTOR",
        }
        pull.reviews.append(review)
        return review

    def new_inline(
        self,
        pull: Pull,
        review: dict[str, Any],
        *,
        path: str,
        line: int | None,
        body: str,
        reply_to: int | None = None,
    ) -> dict[str, Any]:
        self.ids += 1
        comment_id = 5000 + self.ids
        comment: dict[str, Any] = {
            "id": comment_id,
            "node_id": f"PRRC_kwDOAAAAAc{self.ids:08d}",
            "pull_request_review_id": review["id"],
            "diff_hunk": "@@ -0,0 +1,3 @@",
            "path": path,
            "commit_id": _COMMIT,
            "user": _REVIEWER,
            "body": body,
            "created_at": "2026-09-28T10:00:00Z",
            "updated_at": "2026-09-28T10:00:00Z",
            "html_url": f"{github_answers.WEB}/pull/{pull.number}#discussion_r{comment_id}",
            "line": line,
            "side": "RIGHT",
        }
        if reply_to is not None:
            comment["in_reply_to_id"] = reply_to
        pull.inline.append(comment)
        return comment


# --- the handlers ------------------------------------------------------------------

Handler = Callable[[GitHubState, Seen, re.Match[str]], httpx.Response | None]


class Route(NamedTuple):
    method: str
    pattern: re.Pattern[str]
    handler: Handler


def _made(state: GitHubState, match: re.Match[str]) -> Pull | None:
    return state.made.get(int(match["n"]))


def _no_record(state: GitHubState, match: re.Match[str]) -> httpx.Response | None:
    """What a pull-scoped route answers for a pull with no `Pull`: a 404 where there is
    no such pull, and `None` (no route serves it, so the host records it as unrouted)
    for one a host was seeded with."""
    return None if state.seeded(int(match["n"])) else refusal(404, "Not Found")


def _list_pulls(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response:
    wanted = seen.params.get("head", "").split(":", 1)[-1]
    nodes = [n for n in state.nodes() if not wanted or n["headRefName"] == wanted]
    return answer([state.document(n) for n in nodes])


def _create_pull(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response:
    body = seen.body or {}
    head = str(body.get("head", ""))
    if any(p.head == head and not p.merged for p in state.made.values()):
        problem = {
            "resource": "PullRequest",
            "code": "custom",
            "message": f"A pull request already exists for {match['owner']}:{head}.",
        }
        return refusal(422, "Validation Failed", [problem])
    state.new_pull(match["owner"], body)
    return answer(state.document(state.nodes()[-1]), 201)


def _read_pull(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response:
    node = next((n for n in state.nodes() if n["number"] == int(match["n"])), None)
    return refusal(404, "Not Found") if node is None else answer(state.document(node))


def _update_pull(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response | None:
    made = _made(state, match)
    if made is None:
        return _no_record(state, match)
    changes = seen.body or {}
    made.base = str(changes.get("base", made.base))
    made.body = str(changes.get("body", made.body))
    if "state" in changes:
        made.closed = changes["state"] == "closed"
    return _read_pull(state, seen, match)


def _list_reviews(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response | None:
    made = _made(state, match)
    return _no_record(state, match) if made is None else answer(list(made.reviews))


def _list_review_comments(
    state: GitHubState, seen: Seen, match: re.Match[str]
) -> httpx.Response | None:
    made = _made(state, match)
    return _no_record(state, match) if made is None else answer(list(made.inline))


def _list_files(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response | None:
    return _no_record(state, match) if _made(state, match) is None else answer([])


def _read_review(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response | None:
    made = _made(state, match)
    if made is None:
        return _no_record(state, match)
    found = [r for r in made.reviews if r["id"] == int(match["review"])]
    return answer(found[0]) if found else refusal(404, f"Not Found: {seen.path}")


def _reply(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response | None:
    made = _made(state, match)
    if made is None:
        return _no_record(state, match)
    parent = [c for c in made.inline if c["id"] == int(match["note"])]
    if not parent:
        return refusal(404, f"Not Found: {seen.path} names no inline comment")
    review = state.new_review(made, "COMMENTED", "")
    reply = state.new_inline(
        made,
        review,
        path=parent[0]["path"],
        line=parent[0]["line"],
        body=str((seen.body or {}).get("body", "")),
        reply_to=parent[0]["id"],
    )
    return answer(reply, 201)


def _post_comment(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response | None:
    made = _made(state, match)
    if made is None:
        return _no_record(state, match)
    body = str((seen.body or {}).get("body", ""))
    node = state.new_comment(made, body)
    return answer({"id": 2000 + state.ids, "node_id": node, "body": body}, 201)


def _post_status(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response:
    sent = seen.body or {}
    context, status = str(sent.get("context", "")), str(sent.get("state", ""))
    state.statuses.append((match["sha"], context, status))
    return answer({"id": 3000 + len(state.statuses), "context": context, "state": status}, 201)


def _list_repo_labels(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response:
    return page(seen, list(state.repo_labels.values()), state.page_size)


def _create_repo_label(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response:
    body = seen.body or {}
    if state.repo_label(body["name"]):
        error = [{"resource": "Label", "code": "already_exists", "field": "name"}]
        return refusal(422, "Validation Failed", error)
    made = make_label(body["name"], body.get("color", DEFAULT_COLOUR), body.get("description"))
    state.repo_labels[body["name"]] = made
    return answer(made, 201)


def _read_repo_label(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response:
    held = state.repo_label(match["name"])
    return refusal(404, "Not Found") if held is None else answer(state.repo_labels[held])


def _update_repo_label(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response:
    held = state.repo_label(match["name"])
    if held is None:
        return refusal(404, "Not Found")
    body = seen.body or {}
    label = state.repo_labels.pop(held)
    label.update({k: v for k, v in body.items() if k in ("color", "description")})
    label["name"] = body.get("new_name", held)
    state.repo_labels[label["name"]] = label
    return answer(label)


def _pull_labels(state: GitHubState, number: int) -> list[dict]:
    names = state.pr_labels.setdefault(number, [])
    return [state.repo_labels[n] for n in names if n in state.repo_labels]


def _list_pull_labels(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response:
    return answer(_pull_labels(state, int(match["n"])))


def _add_pull_labels(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response:
    names = state.pr_labels.setdefault(int(match["n"]), [])
    body = seen.body
    asked = body.get("labels", []) if isinstance(body, dict) else body
    asked = [a["name"] if isinstance(a, dict) else a for a in asked]
    if seen.method == "PUT":
        names.clear()
    for label in asked:
        held = state.repo_label(label)
        if held is None:  # GitHub creates it, in its own colour
            state.repo_labels[label] = make_label(label, DEFAULT_COLOUR, None)
            held = label
        if held not in names:
            names.append(held)
    return answer([state.repo_labels[n] for n in names])


def _clear_pull_labels(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response:
    state.pr_labels.setdefault(int(match["n"]), []).clear()
    return answer([])


def _remove_pull_label(state: GitHubState, seen: Seen, match: re.Match[str]) -> httpx.Response:
    names = state.pr_labels.setdefault(int(match["n"]), [])
    held = next((n for n in names if n.casefold() == match["name"].casefold()), None)
    if held is None:
        return refusal(404, "Label does not exist")
    names.remove(held)
    return answer(_pull_labels(state, int(match["n"])))


def _route(method: str, path: str, handler: Handler) -> Route:
    return Route(method, re.compile(f"{_REPO}{path}"), handler)


ROUTES: list[Route] = [
    Route("GET", re.compile(r"/repos/(?P<owner>[^/]+)/[^/]+/pulls"), _list_pulls),
    Route("POST", re.compile(r"/repos/(?P<owner>[^/]+)/[^/]+/pulls"), _create_pull),
    _route("GET", r"/pulls/(?P<n>\d+)", _read_pull),
    _route("PATCH", r"/pulls/(?P<n>\d+)", _update_pull),
    _route("GET", r"/pulls/(?P<n>\d+)/reviews", _list_reviews),
    _route("GET", r"/pulls/(?P<n>\d+)/reviews/(?P<review>\d+)", _read_review),
    _route("GET", r"/pulls/(?P<n>\d+)/comments", _list_review_comments),
    _route("POST", r"/pulls/(?P<n>\d+)/comments/(?P<note>\d+)/replies", _reply),
    _route("GET", r"/pulls/(?P<n>\d+)/files", _list_files),
    _route("POST", r"/issues/(?P<n>\d+)/comments", _post_comment),
    _route("POST", r"/statuses/(?P<sha>[^/]+)", _post_status),
    _route("GET", r"/labels", _list_repo_labels),
    _route("POST", r"/labels", _create_repo_label),
    _route("GET", r"/labels/(?P<name>.+)", _read_repo_label),
    _route("PATCH", r"/labels/(?P<name>.+)", _update_repo_label),
    _route("GET", r"/issues/(?P<n>\d+)/labels", _list_pull_labels),
    _route("POST", r"/issues/(?P<n>\d+)/labels", _add_pull_labels),
    _route("PUT", r"/issues/(?P<n>\d+)/labels", _add_pull_labels),
    _route("DELETE", r"/issues/(?P<n>\d+)/labels", _clear_pull_labels),
    _route("DELETE", r"/issues/(?P<n>\d+)/labels/(?P<name>.+)", _remove_pull_label),
]


def serve(state: GitHubState, seen: Seen) -> httpx.Response | None:
    """The table's answer to a request, or `None` when no route serves it."""
    for route in ROUTES:
        found = route.pattern.fullmatch(seen.path)
        if found and route.method == seen.method:
            return route.handler(state, seen, found)
    return None
