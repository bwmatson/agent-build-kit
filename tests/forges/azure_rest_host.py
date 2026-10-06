"""Azure DevOps at the HTTP boundary: a stand-in answering the REST calls.

What it receives is the request the forge's transport sends (method, path,
query, JSON body); what it sends back is the raw document the service sends,
from `azure_answers`, wrapped as the service wraps a list (`{"value": [...],
"count": n}`). It does what the real service does that a canned answer cannot:

- lists pull requests by `searchCriteria.status` and `searchCriteria.sourceRefName`,
  a page at a time (`$top`/`$skip`, never more than `PAGE` a page);
- pages policy evaluations by `$top`/`$skip`, never more than `policy_page` a
  page, and sends no continuation token (the reference documents none);
- answers 401 to a Bearer token in `rejected_tokens`, as for an expired one;
- answers a ref delete with `success: false` and `ref_status` when one is set;
- pages an iteration's changes by `$top`/`$skip`, saying where the next page
  starts in `nextSkip`/`nextTop` (zero once there is none);
- keeps every status posted, each with an id of its own, and labels
  case-insensitively unique and removed by name.

A route it does not know fails the test rather than answering emptily: a forge
reaching for a resource nobody expected is the thing under test.
"""

from __future__ import annotations

import json
import re
import threading
import time
from copy import deepcopy
from typing import Any

import httpx

from tests.forges import azure_answers

PAGE = 100
PROJECT_ID = "11111111-2222-3333-4444-555555555555"
NO_OBJECT = "0" * 40
JSON = {"content-type": "application/json; charset=utf-8"}

_ROUTE = re.compile(r"^/(?P<org>[^/]+)/(?P<project>[^/]+)/_apis/(?P<rest>.*)$")
_GIT = re.compile(r"^git/repositories/(?P<repo>[^/]+)(?:/(?P<tail>.*))?$")


def pull(**overrides: Any) -> dict:
    """A pull request as the list answers it: with the repository and project it
    belongs to, which the policy evaluation artifact id is built from."""
    return {
        **azure_answers.pull(**overrides),
        "repository": {
            "id": azure_answers.GUID,
            "name": "Some Repo",
            "project": {"id": PROJECT_ID, "name": "Some Project", "state": "wellFormed"},
        },
    }


def listed(document: dict) -> dict:
    """A document from `azure_answers`, as the list endpoint carries it."""
    return {**document, "repository": pull()["repository"]}


def answer(
    body: object, status: int = 200, headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, content=json.dumps(body), headers={**JSON, **(headers or {})})


def refusal(status: int, message: str, type_key: str = "GitPullRequestException") -> httpx.Response:
    """An error as Azure DevOps sends one."""
    body = {"$id": "1", "message": message, "typeKey": type_key, "errorCode": 0}
    return answer(body, status)


class Seen:
    """One request that reached the host, normalised for assertions.

    `route` is the path after the repository (`pullrequests/162/threads`), or
    after `_apis/` for the resources that are not the repository's
    (`policy/evaluations`), lower-cased as the service is case-insensitive.
    """

    def __init__(self, request: httpx.Request, route: str, body: Any) -> None:
        self.request = request
        self.method = request.method
        self.route = route
        self.params = dict(request.url.params)
        self.body = body
        self.authorization = request.headers.get("authorization", "")

    def __repr__(self) -> str:
        return f"{self.method} {self.route} {self.params} {self.body}"


class RestHost(httpx.MockTransport):
    def __init__(
        self,
        *pulls: dict,
        threads: dict[int, list[dict]] | None = None,
        policies: dict[int, list[dict]] | None = None,
        builds: dict[int, str] | None = None,
        statuses: dict[int, list[dict]] | None = None,
        labels: dict[int, list[str]] | None = None,
        refs: dict[str, str] | None = None,
        changes: list[dict] | None = None,
        branch_policies: list[dict] | None = None,
        policy_page: int = 1000,
        ref_status: str = "",
        change_page: int = 1000,
        delay: float = 0.0,
        refuse: dict[tuple[str, str], httpx.Response] | None = None,
    ) -> None:
        self.pulls = [deepcopy(p) if "repository" in p else listed(p) for p in pulls]
        self.threads = threads or {}
        self.policies = policies or {}
        self.builds = builds or {}
        self.statuses: dict[int, list[dict]] = {k: list(v) for k, v in (statuses or {}).items()}
        self.labels: dict[int, list[dict]] = {}
        for number, names in (labels or {}).items():
            self.labels[number] = [self._label(name) for name in names]
        self.refs = refs or {}
        self.changes = changes if changes is not None else azure_answers.CHANGES["changeEntries"]
        self.branch_policies = branch_policies or []
        self.policy_page = policy_page
        self.ref_status = ref_status
        self.rejected_tokens: set[str] = set()
        self.change_page = change_page
        self.delay = delay
        self.refuse = refuse or {}
        self.seen: list[Seen] = []
        self._lock = threading.Lock()
        self._in_flight = 0
        self.peak = 0
        super().__init__(self._handle)

    # --- what a test asks ---------------------------------------------------------

    def calls(self, method: str | None = None, route: str | None = None) -> list[Seen]:
        return [
            s
            for s in self.seen
            if (method is None or s.method == method) and (route is None or s.route == route)
        ]

    def writes(self) -> list[Seen]:
        return [s for s in self.seen if s.method != "GET"]

    def label_names(self, number: int) -> list[str]:
        return [label["name"] for label in self.labels.get(number, [])]

    # --- the service --------------------------------------------------------------

    def _handle(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self._in_flight += 1
            self.peak = max(self.peak, self._in_flight)
        try:
            if self.delay:
                time.sleep(self.delay)
            return self._route(request)
        finally:
            with self._lock:
                self._in_flight -= 1

    def _route(self, request: httpx.Request) -> httpx.Response:
        match = _ROUTE.match(request.url.path)
        if not match:
            raise AssertionError(f"not an Azure DevOps REST path: {request.url.path}")
        rest = match["rest"].strip("/")
        git = _GIT.match(rest)
        route = (git["tail"] or "") if git else rest
        route = route.lower()
        body = json.loads(request.content) if request.content else None
        with self._lock:
            self.seen.append(Seen(request, route, body))
        if request.headers.get("authorization", "").removeprefix("Bearer ") in self.rejected_tokens:
            return refusal(401, "TF400813: The user is not authorized to access this resource.")
        refused = self.refuse.get((request.method, route))
        if refused is not None:
            return refused
        found = self._dispatch(request, route, body, in_repo=bool(git))
        if found is None:
            raise AssertionError(f"the stand-in host was not expecting {request.method} {route}")
        return found

    def _dispatch(
        self, request: httpx.Request, route: str, body: Any, *, in_repo: bool
    ) -> httpx.Response | None:
        method = request.method
        params = request.url.params
        if not in_repo:
            return self._outside_repo(method, route, params, body)
        if route == "" and method == "GET":
            return answer({"id": azure_answers.GUID, "name": "Some Repo"})
        if route == "pullrequests":
            if method == "GET":
                return self._list(params)
            if method == "POST":
                return self._create(body)
        refs = re.fullmatch(r"pullrequests/(\d+)(?:/(.*))?", route)
        if refs:
            return self._pull_route(method, int(refs[1]), refs[2] or "", params, body)
        commit = re.fullmatch(r"commits/([^/]+)/statuses", route)
        if commit and method == "POST":
            return answer({**body, "id": 1})
        if route == "refs":
            if method == "GET":
                return self._refs(params)
            if method == "POST":
                update = {"success": not self.ref_status, "name": body[0]["name"]}
                if self.ref_status:
                    update["updateStatus"] = self.ref_status
                return answer({"value": [update], "count": 1})
        return None

    def _outside_repo(
        self, method: str, route: str, params: httpx.QueryParams, body: Any
    ) -> httpx.Response | None:
        if route == "policy/evaluations" and method == "GET":
            return self._evaluations(params)
        if route.startswith("policy/evaluations/") and method == "PATCH":
            return answer({"evaluationId": route.rsplit("/", 1)[1], "status": "queued"})
        if route == "policy/configurations" and method == "GET":
            return answer({"value": self.branch_policies, "count": len(self.branch_policies)})
        build = re.fullmatch(r"build/builds/(\d+)", route)
        if build and method == "GET":
            number = int(build[1])
            return answer(
                {
                    "id": number,
                    "buildNumber": f"2026.{number}",
                    "status": "completed",
                    "result": self.builds[number],
                    "reason": "pullRequest",
                    "queueTime": "2026-09-24T18:02:11.483Z",
                    "finishTime": "2026-09-24T18:09:00.000Z",
                }
            )
        return None

    def _list(self, params: httpx.QueryParams) -> httpx.Response:
        status = params.get("searchCriteria.status", "active")
        source = params.get("searchCriteria.sourceRefName", "")
        top = min(int(params.get("$top", PAGE)), PAGE)
        skip = int(params.get("$skip", 0))
        matching = [
            p
            for p in self.pulls
            if (status == "all" or p["status"] == status)
            and (not source or p["sourceRefName"] == source)
        ]
        page = matching[skip : skip + top]
        return answer({"value": page, "count": len(page)})

    def _create(self, body: dict) -> httpx.Response:
        number = 300 + len(self.pulls)
        made = pull(
            pullRequestId=number,
            sourceRefName=body["sourceRefName"],
            targetRefName=body["targetRefName"],
            title=body["title"],
        )
        self.pulls.append(made)
        return answer(made, 201)

    def _find(self, number: int) -> dict:
        return next(p for p in self.pulls if p["pullRequestId"] == number)

    def _pull_route(
        self, method: str, number: int, tail: str, params: httpx.QueryParams, body: Any
    ) -> httpx.Response | None:
        if tail == "":
            if method == "GET":
                return answer(self._find(number))
            if method == "PATCH":
                found = self._find(number)
                found.update(body)
                return answer(found)
        if tail == "threads":
            if method == "GET":
                items = self.threads.get(number, [])
                return answer(azure_answers.threads(*items))
            if method == "POST":
                return answer({"id": 900, "comments": [{"id": 1, **body["comments"][0]}]}, 200)
        comment = re.fullmatch(r"threads/(\d+)/comments", tail)
        if comment and method == "POST":
            return answer({"id": 4, **body}, 200)
        if tail == "labels":
            return self._label_route(method, number, body)
        named = re.fullmatch(r"labels/(.+)", tail)
        if named and method == "DELETE":
            return self._unlabel(number, named[1])
        if tail == "statuses":
            if method == "GET":
                items = self.statuses.get(number, [])
                return answer({"value": items, "count": len(items)})
            if method == "POST":
                stored = {**body, "id": len(self.statuses.get(number, [])) + 1}
                self.statuses.setdefault(number, []).append(stored)
                return answer(stored, 200)
        if tail == "iterations" and method == "GET":
            return answer(azure_answers.ITERATIONS)
        changes = re.fullmatch(r"iterations/(\d+)/changes", tail)
        if changes and method == "GET":
            return self._changes(params)
        return None

    def _evaluations(self, params: httpx.QueryParams) -> httpx.Response:
        artifact = params.get("artifactId", "")
        match = re.fullmatch(rf"vstfs:///CodeReview/CodeReviewId/{PROJECT_ID}/(\d+)", artifact)
        if not match:
            raise AssertionError(f"not the artifact id of a pull request here: {artifact!r}")
        items = self.policies.get(int(match[1]), [])
        top = min(int(params.get("$top", self.policy_page)), self.policy_page)
        skip = int(params.get("$skip", 0))
        page = items[skip : skip + top]
        return answer({"value": page, "count": len(page)})

    def _changes(self, params: httpx.QueryParams) -> httpx.Response:
        top = min(int(params.get("$top", self.change_page)), self.change_page)
        skip = int(params.get("$skip", 0))
        page = self.changes[skip : skip + top]
        more = skip + top < len(self.changes)
        return answer(
            {
                "changeEntries": page,
                "nextSkip": skip + top if more else 0,
                "nextTop": top if more else 0,
            }
        )

    def _refs(self, params: httpx.QueryParams) -> httpx.Response:
        wanted = params.get("filter", "")
        found = [
            {"name": f"refs/{name}", "objectId": oid}
            for name, oid in self.refs.items()
            if name.startswith(wanted)
        ]
        return answer({"value": found, "count": len(found)})

    def _label(self, name: str) -> dict:
        return {
            "id": f"00000000-0000-0000-0000-{abs(hash(name.casefold())) % 10**12:012d}",
            "name": name,
            "active": True,
        }

    def _label_route(self, method: str, number: int, body: Any) -> httpx.Response | None:
        held = self.labels.setdefault(number, [])
        if method == "GET":
            return answer({"count": len(held), "value": list(held)})
        if method == "POST":
            same = next((x for x in held if x["name"].casefold() == body["name"].casefold()), None)
            if same is None:
                same = self._label(body["name"])
                held.append(same)
            return answer(same)
        return None

    def _unlabel(self, number: int, name: str) -> httpx.Response:
        held = self.labels.setdefault(number, [])
        gone = next((x for x in held if x["name"].casefold() == name.casefold()), None)
        if gone is None:
            return refusal(404, "TF401088: The label could not be found.")
        held.remove(gone)
        return httpx.Response(200)
