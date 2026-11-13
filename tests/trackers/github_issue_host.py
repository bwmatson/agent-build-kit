"""GitHub issues at the HTTP boundary: a stand-in answering the issues REST calls.

It keeps the issues, their sub-issues, the owner's kind and whether it has issue types, and
the body of every create it was sent; the documents it answers with are shaped after the
reference-written bodies under `recorded/github`. A route it does not know fails the test.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Sequence
from copy import deepcopy
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
_ROUTE = re.compile(
    r"^/repos/example/app/issues(?:/(?P<number>\d+))?(?P<rest>/sub_issues|/assignees|/events)?$"
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
    ) -> None:
        """With `lose_create_answer`, the first create is made and answered with a 500.
        `types_enabled` only counts for an organization; of its types, `disabled_types` are
        listed with `is_enabled` false and `missing_types` are not listed. A parent holds at
        most `SUB_ISSUE_LIMIT` sub-issues, as the host does. The repository's labels are kept:
        an issue is updated only with labels that exist, one is made by `POST .../labels`, and
        an assignment is an event with a time, as the host records it."""
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
    ) -> str:
        """An issue that already exists, as a person made it; its number."""
        number = self._store(self._seeded, title, body, labels, type)
        self.issues[number]["state"] = state
        for login in assignees:
            self._assign(number, login)
        if parent is not None:
            self._nest(int(parent), number)
        return str(number)

    def seed_pull_request(self, title: str, body: str = "") -> str:
        """A pull request, which the issues list also returns; its number."""
        number = self._store(self._seeded, title, body, (), None)
        self.issues[number]["pull_request"] = {"url": f"{API}/{number}".replace("issues", "pulls")}
        return str(number)

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

    def _record(self, number: int, kind: str, login: str) -> None:
        self._tick += 1
        self.events.setdefault(number, []).append(
            {
                **self._event,
                "id": self._event["id"] + self._tick,
                "event": kind,
                "created_at": f"2026-10-20T10:00:{self._tick:02d}Z",
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
        return _json(200, self.issues[number])

    def _nest(self, parent: int, child: int) -> None:
        self._children.setdefault(parent, []).append(child)
        self.issues[child]["parent_issue_url"] = f"{self._parent_base}/{parent}"
        self.issues[parent]["sub_issues_summary"]["total"] = len(self._children[parent])

    def _handle(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            return self._route(request)

    def _route(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        if path == "/users/example" and method == "GET":
            return _json(200, self._owner)
        if path == "/user" and method == "GET":
            return _json(200, self._authenticated)
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
            return self._list(request.url.params)
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

    def _list(self, params: httpx.QueryParams) -> httpx.Response:
        """Open issues unless `state` says otherwise, pull requests among them, as the host does."""
        state = params.get("state", "open")
        shown = [
            self.issues[n]
            for n in sorted(self.issues)
            if state == "all" or self.issues[n]["state"] == state
        ]
        return _json(200, self._page(shown, params))

    def _add_sub_issue(self, parent: int, body: dict[str, Any]) -> httpx.Response:
        child = body["sub_issue_id"] - ID_OFFSET
        if child not in self.issues:
            return _json(404, {"message": "Not Found"})
        if len(self._children.get(parent, [])) >= SUB_ISSUE_LIMIT:
            return _json(422, self._refusal)
        self._nest(parent, child)
        return _json(201, self.issues[parent])
