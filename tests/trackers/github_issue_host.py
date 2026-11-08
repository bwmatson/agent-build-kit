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
_ROUTE = re.compile(r"^/repos/example/app/issues(?:/(?P<number>\d+))?(?P<rest>/sub_issues)?$")


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
        sub_issue_limit: int = 100,
        lose_create_answer: bool = False,
    ) -> None:
        """With `lose_create_answer`, the first create is made and answered with a 500.
        `sub_issue_limit` is the most sub-issues a parent holds. `types_enabled` only counts
        for an organization."""
        self.issues = {}
        self.creates = []
        self._children: dict[int, list[int]] = {}
        self._owner = load(
            owner_kind.lower() if owner_kind == "User" else "organization", RECORDED_GITHUB
        ).body
        self._types = load("issue_types", RECORDED_GITHUB).body if types_enabled else None
        self._limit = sub_issue_limit
        self._lose_create_answer = lose_create_answer
        self._template = load("issue", RECORDED_GITHUB).body
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
    ) -> str:
        """An issue that already exists, as a person made it; its number."""
        number = self._store(title, "", labels, type)
        if parent is not None:
            self._nest(int(parent), number)
        return str(number)

    def sub_issues_of(self, parent: str) -> list[str]:
        """The numbers of the sub-issues of an issue, in order."""
        return [str(number) for number in self._children.get(int(parent), [])]

    # --- the service --------------------------------------------------------------

    def _store(self, title: str, body: str, labels: Sequence[str], type: str | None) -> int:
        number = len(self.issues) + 1
        doc = deepcopy(self._template)
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
        return number

    def _nest(self, parent: int, child: int) -> None:
        self._children.setdefault(parent, []).append(child)
        self.issues[child]["parent_issue_url"] = f"{API}/{parent}"
        self.issues[parent]["sub_issues_summary"]["total"] = len(self._children[parent])

    def _handle(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            return self._route(request)

    def _route(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        body = json.loads(request.content) if request.content else {}
        if path == "/users/example" and method == "GET":
            return _json(200, self._owner)
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
            self.issues[number].update(body)
            return _json(200, self.issues[number])
        if number is not None and route["rest"] and method == "GET":
            return _json(200, [self.issues[n] for n in self._children.get(number, [])])
        if number is not None and route["rest"] and method == "POST":
            return self._add_sub_issue(number, body)
        raise AssertionError(f"not a route of the stand-in: {method} {path}")

    def _create(self, body: dict[str, Any]) -> httpx.Response:
        self.creates.append(body)
        number = self._store(
            body["title"], body.get("body", ""), body.get("labels", []), body.get("type")
        )
        if self._lose_create_answer and len(self.creates) == 1:
            return _json(500, {"message": "Server Error"})
        return _json(201, self.issues[number])

    def _list(self, params: httpx.QueryParams) -> httpx.Response:
        size, page = int(params.get("per_page", 30)), int(params.get("page", 1))
        shown = [self.issues[n] for n in sorted(self.issues)]
        return _json(200, shown[(page - 1) * size : page * size])

    def _add_sub_issue(self, parent: int, body: dict[str, Any]) -> httpx.Response:
        child = body["sub_issue_id"] - ID_OFFSET
        if child not in self.issues:
            return _json(404, {"message": "Not Found"})
        if len(self._children.get(parent, [])) >= self._limit:
            message = f"Validation Failed: sub-issues limit of {self._limit} reached"
            return _json(422, {"message": message})
        self._nest(parent, child)
        return _json(201, self.issues[parent])
