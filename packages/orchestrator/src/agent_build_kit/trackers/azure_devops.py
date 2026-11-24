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
import json
import re
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any, cast
from urllib.parse import quote, unquote

import httpx

from agent_build_kit.forges.transport import (
    AzureRest,
    NotFound,
    Response,
    TransportError,
    validated,
)
from agent_build_kit.trackers.azure_probe import probe
from agent_build_kit.trackers.azure_work_item_models import (
    ConnectionDataDoc,
    FieldsDoc,
    RepositoryDoc,
    UpdateDoc,
    WiqlDoc,
    WorkItemDoc,
    WorkItemsDoc,
)
from agent_build_kit.trackers.base import (
    PULL_REQUEST_RELATION,
    Capabilities,
    Change,
    Cursor,
    Identity,
    Item,
    ItemKind,
    NotLinkable,
    ProbeLine,
    Relation,
    StaleRevision,
    UnknownWorkItemType,
    kind_types,
    marker_comment,
    markers_in,
    split_tags,
    with_status_tags,
    without_markers,
)
from agent_build_kit.trackers.config import AzureDevOpsTracker
from agent_build_kit.trackers.manual_parent import ManualParent

PARENT_LINK = "System.LinkTypes.Hierarchy-Reverse"
CHILD_LINK = "System.LinkTypes.Hierarchy-Forward"
ARTIFACT_LINK = "ArtifactLink"
# The kit's relation between two work items to the link type that stands for it.
WORK_ITEM_LINKS = {
    "blocks": "System.LinkTypes.Dependency-Forward",
    "related": "System.LinkTypes.Related",
}
# The kit's name for each field an update reports as changed.
FIELD_NAMES = {
    "System.Title": "title",
    "System.Description": "body",
    "System.State": "state",
    "System.Tags": "tags",
    "System.AssignedTo": "assignee",
}
_PULL_REQUEST_URL = re.compile(
    r"^https://dev\.azure\.com/(?P<organization>[^/]+)/(?P<project>[^/]+)/_git/(?P<repository>[^/]+)"
    r"/pullrequest/(?P<number>\d+)/?$"
)
PATCH = "application/json-patch+json"
# What the service answers a failed revision test with, by its version.
STALE_STATUSES = (409, 412)
# The version `connectionData` is served at.
PREVIEW_VERSION = "7.1-preview.1"
# The version the comments route is served at.
COMMENTS_VERSION = "7.1-preview.4"
# The most work items a batch read takes by id, and the page a change query is asked for.
PAGE_SIZE = 200


def _instant(text: str) -> datetime:
    """A date as the service writes it, which drops the trailing zeros of the fraction, so the
    text of two dates does not order as the dates do."""
    return datetime.fromisoformat(text)


class AzureDevOpsWorkItems:
    def __init__(self, section: AzureDevOpsTracker, *, http: httpx.BaseTransport | None = None):
        self._section = section
        self._rest = AzureRest(http)
        self._identity: Identity | None = None
        self._types: dict[ItemKind, str] = kind_types(section.level_types)
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

    def capabilities(self) -> Capabilities:
        """Revision-checked writes and typed items, which this tracker has."""
        return Capabilities()

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

    def probe(self) -> list[ProbeLine]:
        """What `abk doctor` says about the project: the identity, the types, states, nesting,
        epic, team, paths and work item access, each as its own line."""
        return probe(self._section, self._rest, self.identity)

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

    def add_marker(self, item_id: str, marker: str, expected_revision: str | None = None) -> Item:
        """Tag the item and append the marker comment to its description as it stands (already
        HTML, so it is not escaped again); a person's title, text and tags stay."""
        doc = self._read_level(item_id)
        item = self._to_item(doc)
        if marker in item.markers:
            return item
        tags = [*split_tags(doc.fields.tags), self._tag(marker)]
        description = "\n".join(filter(None, [doc.fields.description, self._comment(marker)]))
        values = {"System.Tags": "; ".join(tags), "System.Description": description}
        return self._patch(item_id, values, expected_revision or str(doc.rev))

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

    def comment(self, item_id: str, text: str) -> None:
        """Add a comment to the item's discussion."""
        self._call(
            "POST",
            f"wit/workitems/{item_id}/comments",
            json={"text": self._html(text)},
            version=COMMENTS_VERSION,
        )

    def set_tag(self, item_id: str, tag: str, present: bool) -> Item:
        """Add or remove one tag (the blocked and in-review markers), leaving the state."""
        doc = self._read_level(item_id)
        tags = list(split_tags(doc.fields.tags))
        if (tag in tags) == present:
            return self._to_item(doc)
        tags = [*tags, tag] if present else [t for t in tags if t != tag]
        return self._patch(item_id, {"System.Tags": "; ".join(tags)}, str(doc.rev))

    def get(self, item_id: str) -> Item:
        """The item, or, read only, the manual epic above the first level, as an item of it."""
        return self._to_item(self._read(item_id), epic_ok=True)

    def children(self, item_id: str) -> Sequence[Item]:
        """The children of an item that are of a configured level; a person's Bug, or any
        other type no level uses, is left out."""
        parent = self._read(item_id)
        ids = [r.url.rsplit("/", 1)[-1] for r in parent.relations if r.rel == CHILD_LINK]
        if not ids:
            return ()
        docs = self._read_many(ids, expand="relations")
        return tuple(self._to_item(doc) for doc in docs if doc.fields.type in self._kinds)

    def read_manual_parent(self, item_id: str) -> ManualParent | None:
        """The work item with this id, of any type (an epic is not one of the levels); none when
        the text is not a work item id or the board has no such item. A read only."""
        if not item_id.isdigit():
            return None
        try:
            doc = self._read(item_id)
        except NotFound:
            return None
        return ManualParent(
            id=str(doc.id),
            title=doc.fields.title,
            type=doc.fields.type,
            in_scope=self._in_scope(doc.fields),
        )

    def _in_scope(self, fields: FieldsDoc) -> bool:
        """Whether the work item sits in the configured project and under the configured area
        path; a document that does not carry them is taken as in scope."""
        section = self._section
        if fields.project is not None and fields.project.casefold() != section.project.casefold():
            return False
        if fields.area_path is None:
            return True
        area, root = fields.area_path.casefold(), section.area_path.casefold()
        return area == root or area.startswith(f"{root}\\")

    def find_manual_parents(self, title: str) -> Sequence[ManualParent]:
        """The work items whose whole title is `title`, in any case: the caller settles case."""
        ids = self._ids_where("System.Title", "=", title)
        candidates = (self.read_manual_parent(item_id) for item_id in ids)
        return [candidate for candidate in candidates if candidate is not None]

    def link(self, item_id: str, relation: str, target_id: str) -> Relation:
        """Relate a work item to a pull request, given as its web address
        (`.../_git/<repository>/pullrequest/<number>`): the artifact link needs the ids of the
        project and the repository, which one read of the repository gives."""
        if relation in WORK_ITEM_LINKS:
            link = {"rel": WORK_ITEM_LINKS[relation], "url": self._url_of(target_id)}
            patch = [{"op": "add", "path": "/relations/-", "value": link}]
            self._call("PATCH", f"wit/workitems/{item_id}", json=patch, content_type=PATCH)
            return Relation(kind=relation, source_id=item_id, target_id=target_id)
        if relation != PULL_REQUEST_RELATION:
            raise ValueError(f"cannot link a work item by {relation!r}")
        found = _PULL_REQUEST_URL.search(target_id)
        if found is None:
            raise NotLinkable(f"not a pull request hosted on Azure DevOps: {target_id!r}")
        section = self._section
        if unquote(found["organization"]).casefold() != section.organization.casefold():
            raise NotLinkable(f"a pull request of another organization: {target_id!r}")
        # The repository is read in the project the address names, which need not be the board's.
        response = self._rest.call(
            section.organization,
            unquote(found["project"]),
            "GET",
            f"git/repositories/{found['repository']}",
        )
        repository = validated(RepositoryDoc, response.data, "repositories", response.text)
        self.link_pull_request(
            item_id,
            project_id=repository.project.id,
            repository_id=repository.id,
            pull_request_id=int(found["number"]),
        )
        return Relation(kind=relation, source_id=item_id, target_id=target_id)

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

    def changed_since(self, cursor: Cursor | None) -> tuple[Sequence[Change], Cursor]:
        """The items in the area path changed since `cursor`, in order of change date and id.

        The service's dates have limited precision, so the cursor is the latest change date seen
        and the ids already handled at that instant. The next listing takes what is left at the
        instant (an item handled there and changed since is later, so it is found again), then
        what is later. Each query is one page, so it repeats until both are empty."""
        state: dict[str, Any] = json.loads(cursor.value) if cursor else {"at": "", "ids": []}
        at: str = state["at"]
        handled: list[int] = list(state["ids"])
        changes: list[Change] = []
        while True:
            listed = self._changed_page(at, handled) if at else None
            if listed is None or not listed.work_items:
                listed = self._changed_page(at, None)
            if not listed.work_items:
                return tuple(changes), Cursor(value=json.dumps({"at": at, "ids": handled}))
            ids = [str(ref.id) for ref in listed.work_items]
            by_id = {doc.id: doc for doc in self._read_many(ids)}
            # An item edited after the query was answered has a later date than the query's;
            # leaving it out keeps the cursor from passing items the page did not list, and the
            # next query lists it again at its new date.
            asked = _instant(listed.as_of) if listed.as_of else None
            for ref in listed.work_items:
                doc = by_id.get(ref.id)
                if doc is None or (asked and _instant(doc.fields.changed_date) > asked):
                    continue
                when = doc.fields.changed_date
                if when != at:
                    at, handled = when, []
                handled.append(doc.id)
                changes.append(self._change_of(doc, when))

    def _changed_page(self, at: str, handled: Sequence[int] | None) -> WiqlDoc:
        """One page of the ids changed at `at` other than `handled`, or, with none given, changed
        after it, in the order of change date and then id."""
        area = self._section.area_path.replace("'", "''")
        query = (
            "SELECT [System.Id] FROM WorkItems WHERE [System.TeamProject] = @project "
            f"AND [System.AreaPath] UNDER '{area}'"
        )
        if handled is not None:
            query += f" AND [System.ChangedDate] = '{at}'"
            if handled:
                query += f" AND [System.Id] NOT IN ({','.join(str(i) for i in handled)})"
        elif at:
            query += f" AND [System.ChangedDate] > '{at}'"
        query += " ORDER BY [System.ChangedDate] ASC, [System.Id] ASC"
        # A date with a time needs `timePrecision`; without `$top` the service answers the
        # whole area path, or refuses it past its result cap.
        return self._query(query, {"timePrecision": "true", "$top": str(PAGE_SIZE)})

    def _read_many(self, ids: Sequence[str], expand: str | None = None) -> list[WorkItemDoc]:
        """The work items with these ids, read at the service's limit of ids to a request; one
        deleted since it was listed is left out."""
        docs: list[WorkItemDoc] = []
        for start in range(0, len(ids), PAGE_SIZE):
            params = {"ids": ",".join(ids[start : start + PAGE_SIZE]), "errorPolicy": "Omit"}
            if expand:
                params["$expand"] = expand
            listed = self._call("GET", "wit/workitems", params)
            found = validated(WorkItemsDoc, listed.data, "workitems", listed.text)
            docs.extend(doc for doc in found.value if doc is not None)
        return docs

    def _change_of(self, doc: WorkItemDoc, when: str) -> Change:
        fields = doc.fields
        ours = bool(self._markers_of(fields)) or any(
            map(self._is_marker_tag, split_tags(fields.tags))
        )
        update = self._call("GET", f"wit/workitems/{doc.id}/updates/{doc.rev}")
        changed = validated(UpdateDoc, update.data, "updates", update.text).fields
        return Change(
            item_id=str(doc.id),
            revision=str(doc.rev),
            fields=tuple(FIELD_NAMES[name] for name in changed if name in FIELD_NAMES),
            who=fields.changed_by.unique_name if fields.changed_by else "",
            when=when,
            foreign=not ours,
        )

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
        return [str(candidate.id) for candidate in self._query(query).work_items]

    def _query(self, query: str, params: dict[str, str] | None = None) -> WiqlDoc:
        response = self._call("POST", "wit/wiql", params, json={"query": query})
        return validated(WiqlDoc, response.data, "wiql", response.text)

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
        text = self._html(body)
        return "\n".join(([text] if body else []) + [self._comment(marker) for marker in markers])

    @staticmethod
    def _html(text: str) -> str:
        """Plain text as the service renders it: HTML collapses a newline, so a line break is
        written as one and read back as one."""
        return html.escape(text, quote=False).replace("\n", "<br>")

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
        return marker_comment(self._section.marker_prefix, marker)

    def _tag(self, marker: str) -> str:
        return f"{self._section.marker_prefix}:{marker}"

    def _markers_of(self, fields: FieldsDoc) -> tuple[str, ...]:
        """The markers in an item's description."""
        return markers_in(self._section.marker_prefix, fields.description)

    def _is_marker_tag(self, tag: str) -> bool:
        """Whether `tag` is one `_tag` wrote, and not a person's."""
        return tag.startswith(f"{self._section.marker_prefix}:")

    def _item(self, response: Response) -> Item:
        return self._to_item(validated(WorkItemDoc, response.data, "workitems", response.text))

    def _to_item(self, doc: WorkItemDoc, *, epic_ok: bool = False) -> Item:
        kind = self._kinds.get(doc.fields.type)
        if kind is None and epic_ok and doc.fields.type == self._section.level_types.get("epic"):
            kind = cast(ItemKind, self._section.levels[0])
        if kind is None:
            raise UnknownWorkItemType(
                f"work item {doc.id} is a {doc.fields.type!r}, which no level of the "
                f"configuration uses (levels: {', '.join(self._section.levels)})"
            )
        description = doc.fields.description
        parent = next(
            (r.url.rsplit("/", 1)[-1] for r in doc.relations if r.rel == PARENT_LINK), None
        )
        return Item(
            id=str(doc.id),
            kind=kind,
            title=doc.fields.title,
            body=html.unescape(
                without_markers(self._section.marker_prefix, description)
                .rstrip("\n")
                .replace("<br>", "\n")
            ),
            state=doc.fields.state,
            assignees=(doc.fields.assigned_to.unique_name,) if doc.fields.assigned_to else (),
            assignee_names=(
                (doc.fields.assigned_to.display_name or doc.fields.assigned_to.unique_name,)
                if doc.fields.assigned_to
                else ()
            ),
            parent_id=parent,
            revision=str(doc.rev),
            url=doc.links.html.href if doc.links and doc.links.html else doc.url,
            markers=self._markers_of(doc.fields),
            tags=tuple(tag for tag in split_tags(doc.fields.tags) if not self._is_marker_tag(tag)),
            kit_state=self._section.kit_state(doc.fields.type, doc.fields.state),
        )
