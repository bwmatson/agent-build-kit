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
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import unquote

import httpx

from agent_build_kit.model import Frozen
from tests.forges.azure_rest_host import Seen, answer, refusal
from tests.trackers.ado_project import ProjectShape
from tests.trackers.ado_recorded import load

REVERSE = "System.LinkTypes.Hierarchy-Reverse"
FORWARD = "System.LinkTypes.Hierarchy-Forward"
BASE = "https://dev.azure.com/example/Some%20Project"
REPOSITORY = load("repository").body
PROJECT_ID = REPOSITORY["project"]["id"]
REPOSITORY_ID = REPOSITORY["id"]
_ROUTE = re.compile(r"^/(?P<org>[^/]+)/(?P<project>[^/]+)(?:/(?P<team>[^/]+))?/_apis/(?P<rest>.*)$")
_NODE = re.compile(
    r"wit/classificationnodes/(?P<tree>areas|iterations)/(?P<path>.+)", re.IGNORECASE
)
_CONDITION = re.compile(
    r"\[([\w.]+)\]\s+(Not Contains Words|Contains Words|Contains|=)\s+'((?:[^']|'')*)'",
    re.IGNORECASE,
)
_CHANGE_CONDITION = re.compile(
    r"\[(System\.ChangedDate|System\.AreaPath)\]\s+(>=|>|UNDER|=)\s+'((?:[^']|'')*)'",
    re.IGNORECASE,
)
_NOT_IN = re.compile(r"\[System\.Id\]\s+NOT IN\s+\(([\d,\s]*)\)", re.IGNORECASE)
_FIELDS = {"title": "System.Title", "state": "System.State"}
# The fields whose text is HTML, which the query language matches only by word.
LONG_TEXT_FIELDS = ("System.Description",)


CLOCK_START = datetime(2026, 10, 21, tzinfo=UTC)
TIME_WITH_DATE_PRECISION = (
    "You cannot supply a time with the date when running a query using date precision"
)


def instant(text: str) -> datetime:
    """A date as the service writes it: the fraction's trailing zeros are dropped, so the text
    of two dates does not order as the dates do."""
    return datetime.fromisoformat(text)


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
    def __init__(
        self,
        *,
        lose_create_answer: bool = False,
        conflict_status: int = 412,
        page_size: int | None = None,
        project: ProjectShape | None = None,
    ) -> None:
        """With `lose_create_answer`, the first create is made and answered with a 500.
        `conflict_status` answers a failed revision test: 409 or 412, by the service's version.
        With `page_size`, a query on the change date answers that many items at most. With
        `project`, it also answers for the project's types, backlog levels, team and paths. A
        token in `rejected_tokens` is answered 401, as an expired one is."""
        self._project = project
        self.comments: dict[str, list[str]] = {}
        # The fields each revision of an item changed, by (item, revision).
        self._revised: dict[tuple[int, int], list[str]] = {}
        self.rejected_tokens: set[str] = set()
        self._acting = ""
        self._page_size = page_size
        self._ticks = 0
        self._read_races: dict[int, str] = {}
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
        area_path: str | None = None,
        changed: str | None = None,
    ) -> str:
        """An item that already exists on the board, as a person made it; its id. `changed` is
        its change date as the service writes it."""
        relations = [{"op": "add", "value": {"rel": REVERSE, "url": self._url(parent)}}]
        fields: dict[str, Any] = {"System.Title": title, "System.Tags": tags}
        if state:
            fields["System.State"] = state
        if assigned_to:
            fields["System.AssignedTo"] = assigned_to
        if area_path:
            fields["System.AreaPath"] = area_path
        if changed:
            fields["System.ChangedDate"] = changed
        return str(self._store(type, fields, relations if parent else [])["id"])

    def as_identity(self, name: str) -> httpx.MockTransport:
        """This host reached by another identity: `connectionData` answers as `name`, and what
        it creates or updates is changed by `name`."""
        return httpx.MockTransport(lambda request: self._handle(request, name))

    def changed_at(self, item_id: str, when: str) -> None:
        """The service stamps an item changed at `when`, as it writes a date."""
        self.items[int(item_id)]["fields"]["System.ChangedDate"] = when

    def edit(self, item_id: str, **fields: str | dict[str, str]) -> None:
        """Another identity changes an item (`title`, `state` or `assigned_to`, the last a unique
        name or a whole identity as the service sends it); the revision moves on."""
        self._write(int(item_id), fields)

    def restamp_on_read(self, item_id: str) -> None:
        """Another identity edits an item between a query that listed it and the read of it: the
        next batch read of the item finds it changed after the query."""
        self._read_races[int(item_id)] = "edit"

    def vanish_on_read(self, item_id: str) -> None:
        """Another identity deletes an item between a query that listed it and the read of it."""
        self._read_races[int(item_id)] = "delete"

    def _on_read(self, number: int) -> None:
        match self._read_races.pop(number, None):
            case "edit":
                self._write(number, {})
            case "delete":
                del self.items[number]

    def _now(self) -> str:
        """The service's clock, which moves one second on each write."""
        moment = CLOCK_START + timedelta(seconds=self._ticks)
        return moment.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def _stamp(self) -> str:
        self._ticks += 1
        return self._now()

    def race(self, item_id: str, **fields: str) -> None:
        """Another identity changes an item just before the next write to it arrives."""
        self._races[int(item_id)] = fields

    def _write(self, number: int, fields: dict[str, Any]) -> None:
        doc = self.items[number]
        self._revised[(number, doc["rev"] + 1)] = [
            "System.AssignedTo" if name == "assigned_to" else _FIELDS.get(name, name)
            for name in fields
        ]
        for name, value in fields.items():
            if name == "assigned_to":
                doc["fields"]["System.AssignedTo"] = _person(value)
            else:
                doc["fields"][_FIELDS.get(name, name)] = value
        doc["rev"] += 1
        doc["fields"]["System.ChangedDate"] = self._stamp()

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
        doc["fields"]["System.ChangedDate"] = self._stamp()
        doc["fields"].update(fields)
        if self._acting:
            doc["fields"]["System.CreatedBy"] = doc["fields"]["System.ChangedBy"] = _person(
                self._acting
            )
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

    def _handle(self, request: httpx.Request, acting: str = "") -> httpx.Response:
        match = _ROUTE.match(unquote(request.url.path))
        if not match:
            raise AssertionError(f"not an Azure DevOps REST path: {request.url.path}")
        route = match["rest"].strip("/").lower()
        body = json.loads(request.content) if request.content else None
        with self._lock:
            self.seen.append(Seen(request, route, body))
            self._acting = acting
            if request.headers.get("authorization", "").removeprefix("Bearer ") in (
                self.rejected_tokens
            ):
                return refusal(401, "TF400813: The user is not authorized to access this resource.")
            return self._route(request, match["rest"].strip("/"), body, match["team"])

    def _connection(self) -> dict[str, Any]:
        """`connectionData` as the acting identity."""
        body = deepcopy(load("connection_data").body)
        if self._acting:
            body["authenticatedUser"]["properties"]["Account"]["$value"] = self._acting
        return body

    def _project_route(self, rest: str, method: str, team: str | None) -> httpx.Response | None:
        """The project's types, backlog levels and paths, from the shape the host was given; None
        for a route that is not one of them. A credential without work item scope is refused
        every route under `wit/` and `work/`."""
        project = self._project
        if project is None or not rest.lower().startswith(("wit/", "work/")):
            return None
        if not project.work_item_access:
            return refusal(
                401,
                "TF400813: The user is not authorized to access this resource.",
                "VssUnauthorizedException",
            )
        if method != "GET":
            return None
        if rest.lower() == "wit/workitemtypes":
            return answer(
                {
                    "count": len(project.types),
                    "value": [
                        {
                            "name": name,
                            "states": [
                                {"name": state, "color": "b2b2b2", "category": "Proposed"}
                                for state in states
                            ],
                        }
                        for name, states in project.types.items()
                    ],
                }
            )
        if rest.lower() == "work/backlogs":
            if team not in project.teams:
                return refusal(
                    404,
                    f"TF50000: The team {team} does not exist in the project.",
                    "ProjectTeamNotFoundException",
                )
            # Top level first, as the levels nest.
            levels = [
                {
                    "id": f"Custom.Backlog{position}",
                    "name": f"Level {position}",
                    "type": "portfolio" if position < len(project.backlogs) - 2 else "requirement",
                    "isHidden": False,
                    "workItemTypes": [{"name": name} for name in names],
                    "defaultWorkItemType": {"name": names[0]},
                }
                for position, names in enumerate(project.backlogs)
            ]
            return answer({"count": len(levels), "value": levels})
        node = _NODE.fullmatch(rest)
        if node:
            known = project.areas if node["tree"].lower() == "areas" else project.iterations
            if node["path"] not in known:
                return refusal(
                    404,
                    f"TF401243: The path {node['path']} does not exist.",
                    "ClassificationNodeNotFoundException",
                )
            return answer({"id": 1, "name": node["path"].rsplit("/", 1)[-1], "hasChildren": False})
        return None

    def _route(
        self, request: httpx.Request, rest: str, body: Any, team: str | None = None
    ) -> httpx.Response:
        method, params = request.method, request.url.params
        shown = self._project_route(rest, method, team)
        if shown is not None:
            return shown
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
        update = re.fullmatch(r"wit/workitems/(\d+)/updates/(\d+)", rest, re.IGNORECASE)
        if update and method == "GET" and int(update[1]) in self.items:
            # An update lists the fields it changed, each with the value it set.
            changed = self._revised.get((int(update[1]), int(update[2])), [])
            values = self.items[int(update[1])]["fields"]
            return answer(
                {
                    "id": int(update[2]),
                    "rev": int(update[2]),
                    "fields": {name: {"newValue": values.get(name)} for name in changed},
                }
            )
        comments = re.fullmatch(r"wit/workitems/(\d+)/comments", rest, re.IGNORECASE)
        if comments and method == "POST" and int(comments[1]) in self.items:
            self.comments.setdefault(comments[1], []).append(body["text"])
            return answer({"id": len(self.comments[comments[1]]), "text": body["text"]})
        if one and method == "PATCH":
            return self._patch(int(one[1]), body, params)
        if rest.lower() == "wit/workitems" and method == "GET":
            ids = [int(i) for i in params["ids"].split(",")]
            for number in ids:
                self._on_read(number)
            if params.get("errorPolicy", "").lower() != "omit" and not all(
                number in self.items for number in ids
            ):
                return refusal(
                    404,
                    "TF401232: Work item does not exist, or you do not have permission to read it.",
                    "WorkItemDoesNotExistException",
                )
            shown = [self._shown(self.items[i], params) if i in self.items else None for i in ids]
            return answer({"count": len(ids), "value": shown})
        if rest.lower() == "connectiondata" and method == "GET":
            if "-preview" not in params.get("api-version", ""):
                return refusal(
                    400,
                    "VS402863: The requested version is in preview; the -preview flag "
                    "must be supplied in the api-version for such requests.",
                    "VssInvalidPreviewVersionException",
                )
            return answer(self._connection())
        repository = re.fullmatch(r"git/repositories/([^/]+)", rest, re.IGNORECASE)
        if repository and method == "GET":
            # The repository exists in its own project only, as on the service.
            project = _ROUTE.match(unquote(request.url.path))["project"]  # type: ignore[index]
            if (project, repository[1]) != (REPOSITORY["project"]["name"], REPOSITORY["name"]):
                return refusal(
                    404,
                    f"TF401019: The Git repository with name or identifier {repository[1]} "
                    f"does not exist in project {project}.",
                    "GitRepositoryNotFoundException",
                )
            return answer(REPOSITORY)
        if rest.lower() == "wit/wiql" and method == "POST":
            if "[System.ChangedDate]" in body["query"]:
                return self._changed_query(body["query"], params)
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
        self._revised[(number, doc["rev"] + 1)] = [
            op["path"].removeprefix("/fields/") for op in ops if op["path"].startswith("/fields/")
        ]
        for op in ops:
            if op["op"] == "add" and op["path"] == "/relations/-":
                doc["relations"].append(op["value"])
            elif op["op"] in ("add", "replace") and op["path"].startswith("/fields/"):
                name, value = op["path"].removeprefix("/fields/"), op["value"]
                if name == "System.AssignedTo" and value == "":
                    # The service answers a cleared identity as an absent field.
                    doc["fields"].pop(name, None)
                else:
                    doc["fields"][name] = _person(value) if name == "System.AssignedTo" else value
        doc["rev"] += 1
        doc["fields"]["System.ChangedDate"] = self._stamp()
        if self._acting:
            doc["fields"]["System.ChangedBy"] = _person(self._acting)
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

    def _changed_query(self, query: str, params: httpx.QueryParams) -> httpx.Response:
        """A query on the change date and the area path, answered in order of change date and
        then id; the service's `>` is strict and `>=` is not.

        A date with a time is refused unless `timePrecision` is true. The answer is cut at `$top`
        and at the page size, and with the page size set and no `$top` a result that is longer
        is refused, as the service refuses one past its cap. It says when it answered."""
        conditions = [
            (field.lower(), operator.upper(), wanted.replace("''", "'"))
            for field, operator, wanted in _CHANGE_CONDITION.findall(query)
        ]
        if params.get("timePrecision", "").lower() != "true" and any(
            "T" in wanted for field, _, wanted in conditions if field == "system.changeddate"
        ):
            return refusal(400, f"VS402351: {TIME_WITH_DATE_PRECISION}.", "WorkItemQueryException")
        left_out = {
            int(number)
            for group in _NOT_IN.findall(query)
            for number in group.split(",")
            if number.strip()
        }
        found = sorted(
            (instant(doc["fields"]["System.ChangedDate"]), number)
            for number, doc in self.items.items()
            if number not in left_out
            and all(self._holds(doc["fields"], *condition) for condition in conditions)
        )
        limits = [int(params["$top"])] if "$top" in params else []
        if self._page_size is not None:
            if not limits and len(found) > self._page_size:
                return refusal(
                    400,
                    f"VS402337: The number of work items returned exceeds the size limit of "
                    f"{self._page_size}. Please add additional filters.",
                    "WorkItemQueryResultSizeLimitExceededException",
                )
            limits.append(self._page_size)
        reply = deepcopy(load("wiql_result").body)
        reply["asOf"] = self._now()
        reply["workItems"] = [
            {"id": number, "url": self._url(str(number))}
            for _, number in found[: min(limits, default=len(found))]
        ]
        return answer(reply)

    @staticmethod
    def _holds(fields: dict[str, Any], field: str, operator: str, wanted: str) -> bool:
        if field == "system.areapath":
            area = fields["System.AreaPath"]
            return area == wanted or area.startswith(wanted + "\\")
        changed, asked = instant(fields["System.ChangedDate"]), instant(wanted)
        return {">": changed > asked, "=": changed == asked}.get(operator, changed >= asked)
