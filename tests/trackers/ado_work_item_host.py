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
_ROUTE = re.compile(r"^/(?P<org>[^/]+)/(?P<project>[^/]+)/_apis/(?P<rest>.*)$")
_CONDITION = re.compile(
    r"\[([\w.]+)\]\s+(Not Contains Words|Contains Words|Contains|=)\s+'((?:[^']|'')*)'",
    re.IGNORECASE,
)
# The fields whose text is HTML, which the query language matches only by word.
LONG_TEXT_FIELDS = ("System.Description",)


class CreateRequest(Frozen):
    """One create call: the type in the route, the body's `add` operations by field path."""

    type: str
    content_type: str
    fields: dict[str, Any]
    relations: list[dict[str, Any]]


class WorkItemHost(httpx.MockTransport):
    def __init__(self, *, lose_create_answer: bool = False) -> None:
        """With `lose_create_answer`, the first create is made and answered with a 500."""
        self.creates: list[CreateRequest] = []
        self.seen: list[Seen] = []
        self.items: dict[int, dict[str, Any]] = {}
        self._lose_create_answer = lose_create_answer
        self._template = load("work_item").body
        self._lock = threading.Lock()
        super().__init__(self._handle)

    # --- what a test asks ---------------------------------------------------------

    def seed(self, type: str, title: str, *, parent: str | None = None) -> str:
        """An item that already exists on the board, as a person made it; its id."""
        relations = [{"op": "add", "value": {"rel": REVERSE, "url": self._url(parent)}}]
        return str(self._store(type, {"System.Title": title}, relations if parent else [])["id"])

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
            return answer(self.items[int(one[1])])
        if rest.lower() == "wit/workitems" and method == "GET":
            ids = [int(i) for i in params["ids"].split(",")]
            return answer({"count": len(ids), "value": [self.items[i] for i in ids]})
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

    def _query(self, query: str) -> httpx.Response:
        """A query on one string field by substring; the service refuses `Contains` on a
        long-text field such as the description, where only `Contains Words` is valid."""
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
            if wanted in doc["fields"].get(field, "")
        ]
        reply = deepcopy(load("wiql_result").body)
        reply["workItems"] = found
        return answer(reply)
