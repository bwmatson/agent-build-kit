"""Azure DevOps work items as a tracker, over the forge's transport.

A create is one JSON Patch to `wit/workitems/$<type>`; the kit's marker is a hidden comment
on the description's last line and also a tag. `find_by_marker` searches the tags, a string
field the query language matches by substring and sees at once (a description is long text,
which it matches only by word, from an index that lags a write), then reads the marker back
from the description of what it found.
Hierarchy is the reverse link on the child, and the forward link on the parent lists children.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from urllib.parse import quote

import httpx

from agent_build_kit.forges.transport import AzureRest, Response, validated
from agent_build_kit.trackers.azure_work_item_models import (
    WiqlDoc,
    WorkItemDoc,
    WorkItemsDoc,
)
from agent_build_kit.trackers.base import Item, ItemKind
from agent_build_kit.trackers.config import KIND_LEVELS, AzureDevOpsTracker

PARENT_LINK = "System.LinkTypes.Hierarchy-Reverse"
CHILD_LINK = "System.LinkTypes.Hierarchy-Forward"
PATCH = "application/json-patch+json"


class UnknownWorkItemType(ValueError):
    """A work item of a type no level of the configuration uses."""


class AzureDevOpsWorkItems:
    def __init__(self, section: AzureDevOpsTracker, *, http: httpx.BaseTransport | None = None):
        self._section = section
        self._rest = AzureRest(http)
        types = section.level_types
        self._types = {kind: types[level] for kind, level in KIND_LEVELS.items() if level in types}
        self._kinds = {type_: kind for kind, type_ in self._types.items()}

    def create(
        self,
        kind: ItemKind,
        title: str,
        body: str = "",
        parent: str | None = None,
        *,
        markers: Sequence[str] = (),
        fields: Mapping[str, str] | None = None,
    ) -> Item:
        section = self._section
        if kind not in self._types:
            raise ValueError(f"kind {kind!r} has no work item type in the configuration")
        # HTML collapses a newline, so a line break is written as one and read back as one.
        text = html.escape(body, quote=False).replace("\n", "<br>")
        description = "\n".join(
            ([text] if body else []) + [self._comment(marker) for marker in markers]
        )
        values = {
            "System.Title": title,
            "System.Description": description,
            "System.AreaPath": section.area_path,
            "System.IterationPath": section.iteration_path,
            **({"System.Tags": "; ".join(self._tag(m) for m in markers)} if markers else {}),
            **(fields or {}),
        }
        patch: list[dict[str, object]] = [
            {"op": "add", "path": f"/fields/{name}", "value": value}
            for name, value in values.items()
        ]
        if parent is not None:
            patch.append(
                {
                    "op": "add",
                    "path": "/relations/-",
                    "value": {"rel": PARENT_LINK, "url": self._url_of(parent)},
                }
            )
        path = f"wit/workitems/${quote(self._types[kind])}"
        return self._item(self._call("POST", path, json=patch, content_type=PATCH))

    def get(self, item_id: str) -> Item:
        return self._item(self._call("GET", f"wit/workitems/{item_id}", {"$expand": "relations"}))

    def children(self, item_id: str) -> Sequence[Item]:
        """The children of an item that are of a configured level; a person's Bug, or any
        other type no level uses, is left out."""
        response = self._call("GET", f"wit/workitems/{item_id}", {"$expand": "relations"})
        parent = validated(WorkItemDoc, response.data, "workitems", response.text)
        ids = [r.url.rsplit("/", 1)[-1] for r in parent.relations if r.rel == CHILD_LINK]
        if not ids:
            return ()
        listed = self._call("GET", "wit/workitems", {"ids": ",".join(ids), "$expand": "relations"})
        found = validated(WorkItemsDoc, listed.data, "workitems", listed.text)
        return tuple(self._to_item(doc) for doc in found.value if doc.fields.type in self._kinds)

    def find_by_marker(self, marker: str) -> Item | None:
        tag = self._tag(marker).replace("'", "''")
        query = (
            "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project "
            f"AND [System.Tags] Contains '{tag}'"
        )
        response = self._call("POST", "wit/wiql", json={"query": query})
        found = validated(WiqlDoc, response.data, "wiql", response.text)
        # `Contains` is a substring match: `change` is also in `change:group`.
        for candidate in found.work_items:
            item = self.get(str(candidate.id))
            if marker in item.markers:
                return item
        return None

    # --- the wire -------------------------------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        *,
        json: object = None,
        content_type: str | None = None,
    ) -> Response:
        section = self._section
        return self._rest.call(
            section.organization,
            section.project,
            method,
            path,
            params=params,
            json=json,
            content_type=content_type,
        )

    def _url_of(self, item_id: str) -> str:
        section = self._section
        return self._rest.url(section.organization, section.project, f"wit/workitems/{item_id}")

    def _comment(self, marker: str) -> str:
        return f"<!-- {self._section.marker_prefix}:{marker} -->"

    def _tag(self, marker: str) -> str:
        return f"{self._section.marker_prefix}:{marker}"

    def _item(self, response: Response) -> Item:
        return self._to_item(validated(WorkItemDoc, response.data, "workitems", response.text))

    def _to_item(self, doc: WorkItemDoc) -> Item:
        kind = self._kinds.get(doc.fields.type)
        if kind is None:
            raise UnknownWorkItemType(
                f"work item {doc.id} is a {doc.fields.type!r}, which no level of the "
                f"configuration uses (levels: {', '.join(self._section.levels)})"
            )
        prefix = re.escape(self._section.marker_prefix)
        marker = re.compile(rf"<!-- {prefix}:(.*?) -->")
        description = doc.fields.description
        parent = next(
            (r.url.rsplit("/", 1)[-1] for r in doc.relations if r.rel == PARENT_LINK), None
        )
        return Item(
            id=str(doc.id),
            kind=kind,
            title=doc.fields.title,
            body=html.unescape(marker.sub("", description).rstrip("\n").replace("<br>", "\n")),
            state=doc.fields.state,
            assignees=(doc.fields.assigned_to.unique_name,) if doc.fields.assigned_to else (),
            parent_id=parent,
            revision=str(doc.rev),
            url=doc.links.html.href if doc.links and doc.links.html else doc.url,
            markers=tuple(marker.findall(description)),
        )
