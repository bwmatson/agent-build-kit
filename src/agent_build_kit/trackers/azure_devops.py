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
from typing import cast, get_args
from urllib.parse import quote

import httpx

from agent_build_kit.forges.transport import (
    AzureRest,
    NotFound,
    Response,
    TransportError,
    validated,
)
from agent_build_kit.trackers.azure_work_item_models import (
    ConnectionDataDoc,
    WiqlDoc,
    WorkItemDoc,
    WorkItemsDoc,
)
from agent_build_kit.trackers.base import (
    Identity,
    Item,
    ItemKind,
    StaleRevision,
    split_tags,
    with_status_tags,
)
from agent_build_kit.trackers.config import AzureDevOpsTracker
from agent_build_kit.trackers.manual_parent import ManualParent

PARENT_LINK = "System.LinkTypes.Hierarchy-Reverse"
CHILD_LINK = "System.LinkTypes.Hierarchy-Forward"
ARTIFACT_LINK = "ArtifactLink"
PATCH = "application/json-patch+json"
# What the service answers a failed revision test with, by its version.
STALE_STATUSES = (409, 412)
# The version `connectionData` is served at.
PREVIEW_VERSION = "7.1-preview.1"


class UnknownWorkItemType(ValueError):
    """A work item of a type no level of the configuration uses."""


class AzureDevOpsWorkItems:
    def __init__(self, section: AzureDevOpsTracker, *, http: httpx.BaseTransport | None = None):
        self._section = section
        self._rest = AzureRest(http)
        self._identity: Identity | None = None
        types = section.level_types
        self._types: dict[ItemKind, str] = {
            cast(ItemKind, level): type_
            for level, type_ in types.items()
            if level in get_args(ItemKind)
        }
        self._kinds: dict[str, ItemKind] = {type_: kind for kind, type_ in self._types.items()}

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
        if parent is not None:
            self._check_parent(kind, parent)
        values = {
            "System.Title": title,
            "System.Description": self._description(body, markers),
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

    def identity(self) -> Identity:
        """The authenticated user, by the unique name an assignment uses."""
        if self._identity is None:
            # Preview only: the service refuses the plain version for this route.
            response = self._call("GET", "connectionData", version=PREVIEW_VERSION)
            data = validated(ConnectionDataDoc, response.data, "connectionData", response.text)
            account = data.authenticated_user.properties.get("Account")
            if account is None or not account.value:
                raise TransportError("connectionData: the authenticated user has no account name")
            self._identity = Identity(name=account.value)
        return self._identity

    def update(
        self, item_id: str, changes: Mapping[str, str], expected_revision: str | None = None
    ) -> Item:
        """`title`, `body`, `state` (the kit's, mapped to the board's) and `tags` (the kit's status
        tags), conditional on the revision: the one given, else the one read now."""
        doc = self._read(item_id)
        item = self._to_item(doc)
        values: dict[str, str] = {}
        for name, value in changes.items():
            if name == "title":
                values["System.Title"] = value
            elif name == "body":
                values["System.Description"] = self._description(value, item.markers)
            elif name == "state":
                values["System.State"] = self._section.board_state(doc.fields.type, value)
            elif name == "tags":
                # Only the kit's status tags are replaced: the markers and a person's tags stay.
                kept = with_status_tags(split_tags(doc.fields.tags), split_tags(value))
                values["System.Tags"] = "; ".join(kept)
            else:
                raise ValueError(f"cannot update {name!r} of a work item")
        return self._patch(item_id, values, expected_revision or item.revision)

    def set_assignee(self, item_id: str, who: str, expected_revision: str | None = None) -> Item:
        doc = self._read_level(item_id)
        return self._patch(item_id, {"System.AssignedTo": who}, expected_revision or str(doc.rev))

    def claim(self, item_id: str) -> bool:
        """Assign the item to the sync identity if nobody holds it; True when it is held by
        it, False when another identity holds it or won the race."""
        me = self.identity().name
        doc = self._read_level(item_id)
        if doc.fields.assigned_to is not None:
            return doc.fields.assigned_to.unique_name == me
        try:
            self._patch(item_id, {"System.AssignedTo": me}, str(doc.rev))
        except StaleRevision:
            return False
        return True

    def set_tag(self, item_id: str, tag: str, present: bool) -> Item:
        """Add or remove one tag (the blocked and in-review markers), leaving the state."""
        doc = self._read_level(item_id)
        tags = list(split_tags(doc.fields.tags))
        if (tag in tags) == present:
            return self._to_item(doc)
        tags = [*tags, tag] if present else [t for t in tags if t != tag]
        return self._patch(item_id, {"System.Tags": "; ".join(tags)}, str(doc.rev))

    def get(self, item_id: str) -> Item:
        return self._to_item(self._read(item_id))

    def children(self, item_id: str) -> Sequence[Item]:
        """The children of an item that are of a configured level; a person's Bug, or any
        other type no level uses, is left out."""
        parent = self._read(item_id)
        ids = [r.url.rsplit("/", 1)[-1] for r in parent.relations if r.rel == CHILD_LINK]
        if not ids:
            return ()
        listed = self._call("GET", "wit/workitems", {"ids": ",".join(ids), "$expand": "relations"})
        found = validated(WorkItemsDoc, listed.data, "workitems", listed.text)
        return tuple(self._to_item(doc) for doc in found.value if doc.fields.type in self._kinds)

    def read_manual_parent(self, item_id: str) -> ManualParent | None:
        """The work item with this id, of any type (an epic is not one of the levels); none when
        the text is not a work item id or the board has no such item. A read only."""
        if not item_id.isdigit():
            return None
        try:
            doc = self._read(item_id)
        except NotFound:
            return None
        return ManualParent(id=str(doc.id), title=doc.fields.title, type=doc.fields.type)

    def find_manual_parents(self, title: str) -> Sequence[ManualParent]:
        """The work items whose whole title is `title`, in any case: the caller settles case."""
        ids = self._ids_where("System.Title", "=", title)
        candidates = (self.read_manual_parent(item_id) for item_id in ids)
        return [candidate for candidate in candidates if candidate is not None]

    def link_pull_request(
        self, item_id: str, *, project_id: str, repository_id: str, pull_request_id: int
    ) -> bool:
        """Attach a pull request to a work item as an artifact link; False when it already
        is attached and nothing was sent."""
        artifact = f"vstfs:///Git/PullRequestId/{project_id}%2F{repository_id}%2F{pull_request_id}"
        doc = self._read_level(item_id)
        if any(r.rel == ARTIFACT_LINK and r.url == artifact for r in doc.relations):
            return False
        link = {"rel": ARTIFACT_LINK, "url": artifact, "attributes": {"name": "Pull Request"}}
        patch = [{"op": "add", "path": "/relations/-", "value": link}]
        self._call("PATCH", f"wit/workitems/{item_id}", json=patch, content_type=PATCH)
        return True

    def find_by_marker(self, marker: str) -> Item | None:
        # `Contains` is a substring match: `change` is also in `change:group`.
        for item_id in self._ids_where("System.Tags", "Contains", self._tag(marker)):
            item = self.get(item_id)
            if marker in item.markers:
                return item
        return None

    def _ids_where(self, field: str, operator: str, text: str) -> list[str]:
        """The ids of the project's work items whose `field` satisfies `operator` against `text`
        (`=` for the whole value, `Contains` for a substring), by one query."""
        escaped = text.replace("'", "''")
        query = (
            "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project "
            f"AND [{field}] {operator} '{escaped}'"
        )
        response = self._call("POST", "wit/wiql", json={"query": query})
        found = validated(WiqlDoc, response.data, "wiql", response.text)
        return [str(candidate.id) for candidate in found.work_items]

    def _read(self, item_id: str) -> WorkItemDoc:
        response = self._call("GET", f"wit/workitems/{item_id}", {"$expand": "relations"})
        return validated(WorkItemDoc, response.data, "workitems", response.text)

    def _read_level(self, item_id: str) -> WorkItemDoc:
        """An item of a configured level, read before anything is written to it; an epic or
        any other type no level uses is refused here, with nothing sent."""
        doc = self._read(item_id)
        self._to_item(doc)
        return doc

    def _patch(self, item_id: str, values: Mapping[str, str], expected_revision: str) -> Item:
        """One JSON Patch that tests the revision first; a conflict is a stale revision."""
        patch: list[dict[str, object]] = [
            {"op": "test", "path": "/rev", "value": int(expected_revision)},
            *({"op": "add", "path": f"/fields/{name}", "value": v} for name, v in values.items()),
        ]
        try:
            response = self._call(
                "PATCH",
                f"wit/workitems/{item_id}",
                {"$expand": "relations"},
                json=patch,
                content_type=PATCH,
            )
        except TransportError as error:
            if error.status in STALE_STATUSES:
                raise StaleRevision(
                    f"work item {item_id} is no longer at revision {expected_revision}"
                ) from error
            raise
        return self._item(response)

    def _description(self, body: str, markers: Sequence[str]) -> str:
        # HTML collapses a newline, so a line break is written as one and read back as one.
        text = html.escape(body, quote=False).replace("\n", "<br>")
        return "\n".join(([text] if body else []) + [self._comment(marker) for marker in markers])

    def _check_parent(self, kind: ItemKind, parent: str) -> None:
        """Read the parent, never write it, and refuse one that is not of the level above
        (the manual epic above the first level)."""
        above = self._section.parent_level(kind)
        if above is None:
            raise ValueError(f"a {kind} item is at the top and has no parent level; got {parent}")
        expected = self._section.level_types[above]
        actual = self._read(parent).fields.type
        if actual != expected:
            raise ValueError(
                f"work item {parent} is a {actual!r}; a {kind} item goes under "
                f"the {above} level, type {expected!r}"
            )

    # --- the wire -------------------------------------------------------------------

    def _call(
        self,
        method: str,
        path: str,
        params: dict[str, str] | None = None,
        *,
        json: object = None,
        content_type: str | None = None,
        version: str | None = None,
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
            version=version,
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
            tags=tuple(
                tag
                for tag in split_tags(doc.fields.tags)
                if not tag.startswith(f"{self._section.marker_prefix}:")
            ),
            kit_state=self._section.kit_state(doc.fields.type, doc.fields.state),
        )
