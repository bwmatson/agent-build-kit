"""GitHub issues at the HTTP boundary: a stand-in answering the issues REST calls.

It keeps the issues, their sub-issues, the owner's kind and whether it has issue types, and
the body of every create it was sent; the documents it answers with are shaped after the
reference-written bodies under `recorded/github`. A route it does not know fails the test.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections.abc import Sequence
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import httpx

from tests.trackers.ado_recorded import load

RECORDED_GITHUB = Path(__file__).parent / "recorded" / "github"
API = "https://api.github.com/repos/example/app/issues"
HTML = "https://github.com/example/app/issues"
# An issue's id is not its number, so a call that sends one for the other fails.
ID_OFFSET = 1000
# The most sub-issues a parent holds, as GitHub documents it (not read from the tracker).
SUB_ISSUE_LIMIT = 100
# The account the tracker's token belongs to, as the recorded authenticated user names it.
SYNC_ACCOUNT = "sync-account"
# Where an Enterprise Server host serves its API, below the host's own address.
ENTERPRISE_PREFIX = "/api/v3"
# The time before the first write the host records; each later one is a second after the last.
EPOCH = datetime(2026, 10, 20, 10, 0, 0, tzinfo=UTC)
_ROUTE = re.compile(
    r"^/repos/example/app/issues(?:/(?P<number>\d+))?"
    r"(?P<rest>/sub_issues|/assignees|/events|/comments)?$"
)


def _json(status: int, data: Any) -> httpx.Response:
    return httpx.Response(status, json=data)


class IssueHost(httpx.MockTransport):
    # Every issue by number, as the host answers it, and the body of each create sent.
    issues: dict[int, dict[str, Any]]
    creates: list[dict[str, Any]]

    def __init__(
        self,
        *,
        owner_kind: Literal["Organization", "User"] = "Organization",
        types_enabled: bool = True,
        disabled_types: Sequence[str] = (),
        missing_types: Sequence[str] = (),
        lose_create_answer: bool = False,
        unauthorized: bool = False,
        repo_exists: bool = True,
        sub_issues_enabled: bool = True,
        token_scopes: str = "repo",
    ) -> None:
        """With `lose_create_answer`, the first create is made and answered with a 500.
        `types_enabled` only counts for an organization; of its types, `disabled_types` are
        listed with `is_enabled` false and `missing_types` are not listed. A parent holds at
        most `SUB_ISSUE_LIMIT` sub-issues, as the host does. The repository's labels are kept:
        an issue is updated only with labels that exist, one is made by `POST .../labels`, and
        an assignment is an event with a time, as the host records it. With `unauthorized`
        every call is refused with 403 and the SAML single sign-on message; without
        `repo_exists` every call about the repository is a 404; without `sub_issues_enabled`
        the sub-issue routes are 404. Every write sets the issue's `updated_at` to the host's
        next second, and a list is answered with an ETag and 304 to a matching
        `If-None-Match`. `token_scopes` is what `/user` says the token may do."""
        # Every request the host was sent, the issues transferred in list answers, how many
        # list answers were 304, and the notes added to each issue.
        self.seen: list[httpx.Request] = []
        self.bodies_sent = 0
        self.not_modified = 0
        self.comments: dict[int, list[str]] = {}
        self._unauthorized = unauthorized
        self._repo_exists = repo_exists
        self._sub_issues_enabled = sub_issues_enabled
        self._scopes = token_scopes
        self._login = SYNC_ACCOUNT
        self.issues = {}
        self.creates = []
        self._children: dict[int, list[int]] = {}
        self._owner = load(
            owner_kind.lower() if owner_kind == "User" else "organization", RECORDED_GITHUB
        ).body
        listed = load("issue_types", RECORDED_GITHUB).body
        self._types = (
            [
                {**entry, "is_enabled": entry["name"] not in disabled_types}
                for entry in listed
                if entry["name"] not in missing_types
            ]
            if types_enabled
            else None
        )
        self._refusal = load("sub_issue_refused", RECORDED_GITHUB).body
        self._lose_create_answer = lose_create_answer
        # What a person's issue and what a create answer look like, and where a sub-issue's
        # parent is written, each as recorded.
        self._seeded = load("issue", RECORDED_GITHUB).body
        self._created = load("issue_created", RECORDED_GITHUB).body
        nested = load("sub_issues", RECORDED_GITHUB).body[0]
        self._parent_base = nested["parent_issue_url"].rsplit("/", 1)[0]
        self._authenticated = load("authenticated_user", RECORDED_GITHUB).body
        self._event = load("issue_event_assigned", RECORDED_GITHUB).body
        self._label = load("label", RECORDED_GITHUB).body
        # The labels the repository has, and the names of the labels made through the API.
        self.repo_labels: set[str] = set()
        self.label_creates: list[str] = []
        # Each issue's assignment events, oldest first, and the people who will be assigned
        # just before the next assignment sent for an issue.
        self.events: dict[int, list[dict[str, Any]]] = {}
        self._racers: dict[int, list[str]] = {}
        self._tick = 0
        self._lock = threading.Lock()
        super().__init__(self._handle)

    # --- what a test asks ---------------------------------------------------------

    def seed(
        self,
        title: str,
        *,
        parent: str | None = None,
        labels: Sequence[str] = (),
        type: str | None = None,
        body: str = "",
        state: Literal["open", "closed"] = "open",
        assignees: Sequence[str] = (),
        updated_at: str | None = None,
        author: str | None = None,
    ) -> str:
        """An issue that already exists, as a person made it; its number. `updated_at` and the
        login of the `author` are the host's own unless given."""
        number = self._store(self._seeded, title, body, labels, type)
        self.issues[number]["state"] = state
        if author is not None:
            self.issues[number]["user"] = self._person(author)
        for login in assignees:
            self._assign(number, login)
        if parent is not None:
            self._nest(int(parent), number)
        if updated_at is not None:
            self.issues[number]["updated_at"] = updated_at
        return str(number)

    def seed_pull_request(self, title: str, body: str = "") -> str:
        """A pull request, which the issues list also returns; its number."""
        number = self._store(self._seeded, title, body, (), None)
        self.issues[number]["pull_request"] = {"url": f"{API}/{number}".replace("issues", "pulls")}
        return str(number)

    def as_identity(self, login: str) -> httpx.MockTransport:
        """The same host, reached with the token of another account."""
        return httpx.MockTransport(lambda request: self._handle(request, login))

    def race(self, number: str, login: str) -> None:
        """`login` is assigned to the issue just before the next assignment sent for it."""
        self._racers.setdefault(int(number), []).append(login)

    def unassign(self, number: str, login: str) -> None:
        """`login` is taken off the issue, as a person does; the assignment stays in its events."""
        self._unassign(int(number), login)

    def assignees_of(self, number: str) -> list[str]:
        """The logins assigned to an issue, in the order they were assigned."""
        return [who["login"] for who in self.issues[int(number)]["assignees"]]

    def labels_of(self, number: str) -> set[str]:
        """The names of the labels an issue carries."""
        return {label["name"] for label in self.issues[int(number)]["labels"]}

    def sub_issues_of(self, parent: str) -> list[str]:
        """The numbers of the sub-issues of an issue, in order."""
        return [str(number) for number in self._children.get(int(parent), [])]

    # --- the service --------------------------------------------------------------

    def _store(
        self,
        template: dict[str, Any],
        title: str,
        body: str,
        labels: Sequence[str],
        type: str | None,
    ) -> int:
        number = len(self.issues) + 1
        doc = deepcopy(template)
        doc.update(
            id=ID_OFFSET + number,
            number=number,
            url=f"{API}/{number}",
            html_url=f"{HTML}/{number}",
            title=title,
            body=body,
            labels=[{"id": 5000 + i, "name": name} for i, name in enumerate(labels)],
            type={"id": 1, "name": type} if type else None,
        )
        self.issues[number] = doc
        self.repo_labels.update(labels)
        return number

    def _person(self, login: str) -> dict[str, Any]:
        return {**self._authenticated, "login": login}

    def _touch(self, number: int) -> str:
        """Set the issue's `updated_at` to the next second, as any write to it does."""
        self._tick += 1
        stamp = (EPOCH + timedelta(seconds=self._tick)).strftime("%Y-%m-%dT%H:%M:%SZ")
        self.issues[number]["updated_at"] = stamp
        return stamp

    def _record(self, number: int, kind: str, login: str) -> None:
        stamp = self._touch(number)
        self.events.setdefault(number, []).append(
            {
                **self._event,
                "id": self._event["id"] + self._tick,
                "event": kind,
                "created_at": stamp,
                "assignee": self._person(login),
            }
        )

    def _assign(self, number: int, login: str) -> None:
        doc = self.issues[number]
        if login in self.assignees_of(str(number)):
            return
        doc["assignees"].append(self._person(login))
        doc["assignee"] = doc["assignees"][0]
        self._record(number, "assigned", login)

    def _unassign(self, number: int, login: str) -> None:
        doc = self.issues[number]
        doc["assignees"] = [who for who in doc["assignees"] if who["login"] != login]
        doc["assignee"] = doc["assignees"][0] if doc["assignees"] else None
        self._record(number, "unassigned", login)

    def _update(self, number: int, body: dict[str, Any]) -> httpx.Response:
        changes = dict(body)
        if "labels" in changes:
            if any(name not in self.repo_labels for name in changes["labels"]):
                return _json(422, {"message": "Validation Failed", "errors": [{"field": "labels"}]})
            changes["labels"] = [
                {"id": 5000 + i, "name": name} for i, name in enumerate(changes["labels"])
            ]
        self.issues[number].update(changes)
        stamp = self._touch(number)
        # The editor is not on the issue; the host keeps who made each edit beside the events.
        self.events.setdefault(number, []).append(
            {
                **self._event,
                "id": self._event["id"] + self._tick,
                "event": "edited",
                "created_at": stamp,
                "actor": self._person(self._login),
            }
        )
        return _json(200, self.issues[number])

    def _nest(self, parent: int, child: int) -> None:
        self._children.setdefault(parent, []).append(child)
        self.issues[child]["parent_issue_url"] = f"{self._parent_base}/{parent}"
        self.issues[parent]["sub_issues_summary"]["total"] = len(self._children[parent])

    def _handle(self, request: httpx.Request, login: str | None = None) -> httpx.Response:
        with self._lock:
            self.seen.append(request)
            self._login = login or SYNC_ACCOUNT
            return self._route(request)

    def _route(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path.removeprefix(ENTERPRISE_PREFIX), request.method
        if self._unauthorized:
            return httpx.Response(
                403,
                json={
                    "message": "Resource protected by organization SAML enforcement. You must "
                    "grant your Personal Access token access to this organization.",
                    "documentation_url": "https://docs.github.com/articles/saml-single-sign-on",
                },
                headers={"x-github-sso": "required; url=https://github.com/orgs/example/sso"},
            )
        if not self._repo_exists and path.startswith("/repos/example/app"):
            return _json(404, {"message": "Not Found"})
        body = json.loads(request.content) if request.content else {}
        if path == "/users/example" and method == "GET":
            return _json(200, self._owner)
        if path == "/user" and method == "GET":
            return httpx.Response(
                200, json=self._person(self._login), headers={"x-oauth-scopes": self._scopes}
            )
        if path == "/repos/example/app/labels" and method == "GET":
            return _json(200, [{**self._label, "name": name} for name in sorted(self.repo_labels)])
        if path == "/repos/example/app/labels" and method == "POST":
            if body["name"] in self.repo_labels:
                return _json(422, {"message": "Validation Failed"})
            self.repo_labels.add(body["name"])
            self.label_creates.append(body["name"])
            return _json(201, {**self._label, "name": body["name"]})
        if path == "/orgs/example/issue-types" and method == "GET":
            if self._owner["type"] != "Organization" or self._types is None:
                return _json(404, {"message": "Not Found"})
            return _json(200, self._types)
        route = _ROUTE.match(path)
        if route is None:
            raise AssertionError(f"not a route of the stand-in: {method} {path}")
        number = int(route["number"]) if route["number"] else None
        if number is not None and number not in self.issues:
            return _json(404, {"message": "Not Found"})
        if number is None and method == "POST":
            return self._create(body)
        if number is None and method == "GET":
            return self._list(request)
        if number is not None and route["rest"] is None and method == "GET":
            return _json(200, self.issues[number])
        if number is not None and route["rest"] is None and method == "PATCH":
            return self._update(number, body)
        if number is not None and route["rest"] == "/events" and method == "GET":
            return _json(200, self._page(self.events.get(number, []), request.url.params))
        if number is not None and route["rest"] == "/assignees" and method == "POST":
            for login in self._racers.pop(number, []):
                self._assign(number, login)
            for login in body["assignees"]:
                self._assign(number, login)
            return _json(201, self.issues[number])
        if number is not None and route["rest"] == "/assignees" and method == "DELETE":
            for login in body["assignees"]:
                self._unassign(number, login)
            return _json(200, self.issues[number])
        if route["rest"] == "/sub_issues" and not self._sub_issues_enabled:
            return _json(404, {"message": "Not Found"})
        if number is not None and route["rest"] == "/comments" and method == "POST":
            self.comments.setdefault(number, []).append(body["body"])
            self._touch(number)
            return _json(201, {"id": 7000 + self._tick, "body": body["body"]})
        if number is not None and route["rest"] == "/sub_issues" and method == "GET":
            shown = [self.issues[n] for n in self._children.get(number, [])]
            return _json(200, self._page(shown, request.url.params))
        if number is not None and route["rest"] == "/sub_issues" and method == "POST":
            return self._add_sub_issue(number, body)
        raise AssertionError(f"not a route of the stand-in: {method} {path}")

    def _create(self, body: dict[str, Any]) -> httpx.Response:
        self.creates.append(body)
        number = self._store(
            self._created,
            body["title"],
            body.get("body", ""),
            body.get("labels", []),
            body.get("type"),
        )
        if self._lose_create_answer and len(self.creates) == 1:
            return _json(500, {"message": "Server Error"})
        return _json(201, self.issues[number])

    @staticmethod
    def _page(shown: list[dict[str, Any]], params: httpx.QueryParams) -> list[dict[str, Any]]:
        size, page = int(params.get("per_page", 30)), int(params.get("page", 1))
        return shown[(page - 1) * size : page * size]

    def _list(self, request: httpx.Request) -> httpx.Response:
        """Open issues unless `state` says otherwise, pull requests among them, as the host does.
        With `since`, those updated at or after it; with `sort=updated`, in that order."""
        params = request.url.params
        state = params.get("state", "open")
        shown = [
            self.issues[n]
            for n in sorted(self.issues)
            if state == "all" or self.issues[n]["state"] == state
        ]
        if since := params.get("since"):
            shown = [doc for doc in shown if doc["updated_at"] >= since]
        if params.get("sort") == "updated":
            shown.sort(
                key=lambda doc: (doc["updated_at"], doc["number"]),
                reverse=params.get("direction", "desc") == "desc",
            )
        page = self._page(shown, params)
        digest = hashlib.sha256(json.dumps([page, str(params)], sort_keys=True).encode())
        etag = f'W/"{digest.hexdigest()[:16]}"'
        if request.headers.get("if-none-match") == etag:
            self.not_modified += 1
            return httpx.Response(304, headers={"etag": etag})
        self.bodies_sent += len(page)
        return httpx.Response(200, json=page, headers={"etag": etag})

    def _add_sub_issue(self, parent: int, body: dict[str, Any]) -> httpx.Response:
        child = body["sub_issue_id"] - ID_OFFSET
        if child not in self.issues:
            return _json(404, {"message": "Not Found"})
        if len(self._children.get(parent, [])) >= SUB_ISSUE_LIMIT:
            return _json(422, self._refusal)
        self._nest(parent, child)
        return _json(201, self.issues[parent])
