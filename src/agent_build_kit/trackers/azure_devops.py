"""Azure DevOps work items as a tracker, over the forge's transport.

A create is one JSON Patch to `wit/workitems/$<type>`; the kit's marker is a hidden comment
on the description's last line, which `find_by_marker` searches for with the query language.
Hierarchy is the reverse link on the child, and the forward link on the parent lists children.
"""

from __future__ import annotations

import html
import re
from collections.abc import Mapping, Sequence
from urllib.parse import quote

import httpx

from agent_build_kit.forges.transport import AzureRest, validated
from agent_build_kit.trackers.azure_work_item_models import (
    WiqlDoc,
    WorkItemDoc,
    WorkItemsDoc,
)
from agent_build_kit.trackers.base import Item, ItemKind
from agent_build_kit.trackers.config import AzureDevOpsTracker

PARENT_LINK = "System.LinkTypes.Hierarchy-Reverse"
CHILD_LINK = "System.LinkTypes.Hierarchy-Forward"
PATCH = "application/json-patch+json"

# The kit's level, by the kind the protocol names it.
_LEVELS: dict[ItemKind, str] = {"feature": "change", "story": "group", "task": "task"}


class AzureDevOpsWorkItems:
    def __init__(self, section: AzureDevOpsTracker, *, http: httpx.BaseTransport | None = None):
        self._section = section
        self._rest = AzureRest(http)
        self._kinds = {
            section.types[level]: kind for kind, level in _LEVELS.items() if level in section.types
        }

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
        level = _LEVELS[kind]
        if level not in section.types:
            raise ValueError(f"kind {kind!r} has no work item type in the configuration")
        description = "\n".join(
            ([html.escape(body, quote=False)] if body else [])
            + [f"<!-- {section.marker_prefix}:{marker} -->" for marker in markers]
        )
        values = {
            "System.Title": title,
            "System.Description": description,
            "System.AreaPath": section.area_path,
            "System.IterationPath": section.iteration_path,
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
        path = f"wit/workitems/${quote(section.types[level])}"
        return self._item(self._call("POST", path, json=patch, content_type=PATCH))

    def get(self, item_id: str) -> Item:
        return self._item(self._call("GET", f"wit/workitems/{item_id}", {"$expand": "relations"}))

    def children(self, item_id: str) -> Sequence[Item]:
        response = self._call("GET", f"wit/workitems/{item_id}", {"$expand": "relations"})
        parent = validated(WorkItemDoc, response.data, "workitems", response.text)
        ids = [r.url.rsplit("/", 1)[-1] for r in parent.relations if r.rel == CHILD_LINK]
        if not ids:
            return ()
        listed = self._call("GET", "wit/workitems", {"ids": ",".join(ids), "$expand": "relations"})
        found = validated(WorkItemsDoc, listed.data, "workitems", listed.text)
        return tuple(self._to_item(doc) for doc in found.value)

    def find_by_marker(self, marker: str) -> Item | None:
        text = f"<!-- {self._section.marker_prefix}:{marker} -->".replace("'", "''")
        query = (
            "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project "
            f"AND [System.Description] Contains '{text}'"
        )
        response = self._call("POST", "wit/wiql", json={"query": query})
        found = validated(WiqlDoc, response.data, "wiql", response.text)
        if not found.work_items:
            return None
        return self.get(str(found.work_items[0].id))

    # --- the wire -------------------------------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        *,
        json: object = None,
        content_type: str | None = None,
    ):
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
        return (
            f"{AzureRest.host}/{quote(section.organization)}/{quote(section.project)}"
            f"/_apis/wit/workitems/{item_id}"
        )

    def _item(self, response) -> Item:
        return self._to_item(validated(WorkItemDoc, response.data, "workitems", response.text))

    def _to_item(self, doc: WorkItemDoc) -> Item:
        prefix = re.escape(self._section.marker_prefix)
        marker = re.compile(rf"<!-- {prefix}:(.*?) -->")
        description = doc.fields.description
        parent = next(
            (r.url.rsplit("/", 1)[-1] for r in doc.relations if r.rel == PARENT_LINK), None
        )
        return Item(
            id=str(doc.id),
            kind=self._kinds[doc.fields.type],
            title=doc.fields.title,
            body=html.unescape(marker.sub("", description).rstrip("\n")),
            state=doc.fields.state,
            assignees=(doc.fields.assigned_to.unique_name,) if doc.fields.assigned_to else (),
            parent_id=parent,
            revision=str(doc.rev),
            url=doc.links.html.href if doc.links and doc.links.html else doc.url,
            markers=tuple(marker.findall(description)),
        )
