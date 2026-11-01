"""Azure DevOps work items at the HTTP boundary: a stand-in answering the REST calls.

What it receives is the request the transport sends (JSON Patch bodies to
`wit/workitems/$<type>`, `wit/wiql` queries); what it sends back is the document the
service sends, shaped after the reference-written `work_item` body. A route it does not know
fails the test. It keeps the items it creates, the forward link on a parent for each child
made under it, and a record of every request.
"""

from __future__ import annotations

import json
import re
import threading
from copy import deepcopy
from typing import Any
from urllib.parse import unquote

import httpx

from agent_build_kit.model import Frozen
from tests.forges.azure_rest_host import Seen, answer, refusal
from tests.trackers.ado_recorded import load

REVERSE = "System.LinkTypes.Hierarchy-Reverse"
FORWARD = "System.LinkTypes.Hierarchy-Forward"
BASE = "https://dev.azure.com/example/Some%20Project"
PROJECT_ID = "project-guid"
_ROUTE = re.compile(r"^/(?P<org>[^/]+)/(?P<project>[^/]+)/_apis/(?P<rest>.*)$")
_CONDITION = re.compile(
    r"\[([\w.]+)\]\s+(Not Contains Words|Contains Words|Contains|=)\s+'((?:[^']|'')*)'",
    re.IGNORECASE,
)
_FIELDS = {"title": "System.Title", "state": "System.State"}
# The fields whose text is HTML, which the query language matches only by word.
LONG_TEXT_FIELDS = ("System.Description",)


def _person(who: Any) -> Any:
    """An identity field as the service answers it, from a unique name or an identity."""
    if not isinstance(who, str):
        return who
    return {"displayName": who, "uniqueName": who, "id": f"id-{who}"}


class CreateRequest(Frozen):
    """One create call: the type in the route, the body's `add` operations by field path."""

    type: str
    content_type: str
    fields: dict[str, Any]
    relations: list[dict[str, Any]]


class WorkItemHost(httpx.MockTransport):
    def __init__(self, *, lose_create_answer: bool = False, conflict_status: int = 412) -> None:
        """With `lose_create_answer`, the first create is made and answered with a 500.
        `conflict_status` answers a failed revision test: 409 or 412, by the service's version."""
        self._conflict_status = conflict_status
        self._races: dict[int, dict[str, Any]] = {}
        self.creates: list[CreateRequest] = []
        self.seen: list[Seen] = []
        self.items: dict[int, dict[str, Any]] = {}
        self._lose_create_answer = lose_create_answer
        self._template = load("work_item").body
        self._lock = threading.Lock()
        super().__init__(self._handle)

    # --- what a test asks ---------------------------------------------------------

    def seed(
        self,
        type: str,
        title: str,
        *,
        parent: str | None = None,
        state: str | None = None,
        assigned_to: str | None = None,
        tags: str = "",
    ) -> str:
        """An item that already exists on the board, as a person made it; its id."""
        relations = [{"op": "add", "value": {"rel": REVERSE, "url": self._url(parent)}}]
        fields: dict[str, Any] = {"System.Title": title, "System.Tags": tags}
        if state:
            fields["System.State"] = state
        if assigned_to:
            fields["System.AssignedTo"] = assigned_to
        return str(self._store(type, fields, relations if parent else [])["id"])

    def edit(self, item_id: str, **fields: str) -> None:
        """Another identity changes an item (`title`, `state` or `assigned_to`); the
        revision moves on."""
        self._write(int(item_id), fields)

    def race(self, item_id: str, **fields: str) -> None:
        """Another identity changes an item just before the next write to it arrives."""
        self._races[int(item_id)] = fields

    def _write(self, number: int, fields: dict[str, str]) -> None:
        doc = self.items[number]
        for name, value in fields.items():
            if name == "assigned_to":
                doc["fields"]["System.AssignedTo"] = _person(value)
            else:
                doc["fields"][_FIELDS.get(name, name)] = value
        doc["rev"] += 1

    def calls(self, method: str | None = None, route: str | None = None) -> list[Seen]:
        return [
            s
            for s in self.seen
            if (method is None or s.method == method) and (route is None or s.route == route)
        ]

    # --- the service --------------------------------------------------------------

    def _url(self, item_id: str | None) -> str:
        return f"{BASE}/_apis/wit/workItems/{item_id}"

    def _store(
        self, type: str, fields: dict[str, Any], relations: list[dict[str, Any]]
    ) -> dict[str, Any]:
        number = len(self.items) + 1
        doc = deepcopy(self._template)
        doc.update(id=number, rev=1, url=self._url(str(number)), relations=[])
        doc["_links"]["html"]["href"] = f"{BASE}/_workitems/edit/{number}"
        doc["fields"].update(
            {"System.WorkItemType": type, "System.State": "To Do", "System.Description": ""}
        )
        doc["fields"].update(fields)
        if "System.AssignedTo" in fields:
            doc["fields"]["System.AssignedTo"] = _person(fields["System.AssignedTo"])
        for relation in relations:
            doc["relations"].append(
                {"rel": relation["value"]["rel"], "url": relation["value"]["url"]}
            )
            if relation["value"]["rel"] == REVERSE:
                parent = self.items[int(relation["value"]["url"].rsplit("/", 1)[-1])]
                parent["relations"].append({"rel": FORWARD, "url": self._url(str(number))})
        self.items[number] = doc
        return doc

    def _handle(self, request: httpx.Request) -> httpx.Response:
        match = _ROUTE.match(unquote(request.url.path))
        if not match:
            raise AssertionError(f"not an Azure DevOps REST path: {request.url.path}")
        route = match["rest"].strip("/").lower()
        body = json.loads(request.content) if request.content else None
        with self._lock:
            self.seen.append(Seen(request, route, body))
            return self._route(request, match["rest"].strip("/"), body)

    def _route(self, request: httpx.Request, rest: str, body: Any) -> httpx.Response:
        method, params = request.method, request.url.params
        created = re.fullmatch(r"wit/workitems/\$(.+)", rest, re.IGNORECASE)
        if created and method == "POST":
            return self._create(request, created[1], body)
        one = re.fullmatch(r"wit/workitems/(\d+)", rest, re.IGNORECASE)
        if one and method == "GET":
            if int(one[1]) not in self.items:
                return refusal(
                    404,
                    f"TF401232: Work item {one[1]} does not exist, or you do not have "
                    "permission to read it.",
                    "WorkItemDoesNotExistException",
                )
            return answer(self._shown(self.items[int(one[1])], params))
        if one and method == "PATCH":
            return self._patch(int(one[1]), body, params)
        if rest.lower() == "wit/workitems" and method == "GET":
            ids = [int(i) for i in params["ids"].split(",")]
            shown = [self._shown(self.items[i], params) for i in ids]
            return answer({"count": len(ids), "value": shown})
        if rest.lower() == "connectiondata" and method == "GET":
            if "-preview" not in params.get("api-version", ""):
                return refusal(
                    400,
                    "VS402863: The requested version is in preview; the -preview flag "
                    "must be supplied in the api-version for such requests.",
                    "VssInvalidPreviewVersionException",
                )
            return answer(load("connection_data").body)
        repository = re.fullmatch(r"git/repositories/([^/]+)", rest, re.IGNORECASE)
        if repository and method == "GET":
            return answer(
                {
                    "id": f"repo-{repository[1]}",
                    "name": repository[1],
                    "project": {"id": PROJECT_ID, "name": "Some Project"},
                }
            )
        if rest.lower() == "wit/wiql" and method == "POST":
            return self._query(body["query"])
        raise AssertionError(f"the stand-in host was not expecting {method} {rest}")

    def _create(
        self, request: httpx.Request, type: str, ops: list[dict[str, Any]]
    ) -> httpx.Response:
        fields = {
            op["path"].removeprefix("/fields/"): op["value"]
            for op in ops
            if "/fields/" in op["path"]
        }
        relations = [op for op in ops if op["path"].startswith("/relations")]
        self.creates.append(
            CreateRequest(
                type=type,
                content_type=request.headers["content-type"],
                fields=fields,
                relations=[op["value"] for op in relations],
            )
        )
        made = self._store(type, fields, relations)
        if self._lose_create_answer and len(self.creates) == 1:
            return httpx.Response(500, text="The service is unavailable.")
        return answer(made)

    @staticmethod
    def _shown(doc: dict[str, Any], params: httpx.QueryParams) -> dict[str, Any]:
        """The item as the service answers it: its relations only when `$expand` asks."""
        if "relations" in params.get("$expand", "").lower():
            return doc
        return {key: value for key, value in doc.items() if key != "relations"}

    def _patch(
        self, number: int, ops: list[dict[str, Any]], params: httpx.QueryParams
    ) -> httpx.Response:
        """An update: a `test` on `/rev` that fails changes nothing; field and relation
        operations are applied and the revision moves on once."""
        if number in self._races:
            self._write(number, self._races.pop(number))
        doc = self.items[number]
        for op in ops:
            if op["op"] == "test" and op["path"] == "/rev" and op["value"] != doc["rev"]:
                return refusal(
                    self._conflict_status,
                    f"VS403357: Revision {doc['rev']} of work item {number} is not {op['value']}.",
                    "WorkItemRevisionMismatchException",
                )
        for op in ops:
            if op["op"] == "add" and op["path"] == "/relations/-":
                doc["relations"].append(op["value"])
            elif op["op"] in ("add", "replace") and op["path"].startswith("/fields/"):
                name, value = op["path"].removeprefix("/fields/"), op["value"]
                doc["fields"][name] = _person(value) if name == "System.AssignedTo" else value
        doc["rev"] += 1
        return answer(self._shown(doc, params))

    @staticmethod
    def _matches(operator: str, wanted: str, value: str) -> bool:
        """`=` is the whole value in any case, as the service compares; the rest a substring."""
        if operator == "=":
            return wanted.casefold() == value.casefold()
        return wanted in value

    def _query(self, query: str) -> httpx.Response:
        """A query on one string field by substring, or by whole value for `=`; the service
        refuses `Contains` on a long-text field such as the description, where only
        `Contains Words` is valid."""
        condition = _CONDITION.findall(query)[-1]
        field, operator, wanted = condition[0], condition[1], condition[2].replace("''", "'")
        if field in LONG_TEXT_FIELDS and operator.lower() == "contains":
            return refusal(
                400,
                f"VS403474: The operator Contains cannot be used with the field {field}.",
                "WorkItemQueryClauseInvalidException",
            )
        found = [
            {"id": number, "url": self._url(str(number))}
            for number, doc in self.items.items()
            if self._matches(operator, wanted, doc["fields"].get(field, ""))
        ]
        reply = deepcopy(load("wiql_result").body)
        reply["workItems"] = found
        return answer(reply)
