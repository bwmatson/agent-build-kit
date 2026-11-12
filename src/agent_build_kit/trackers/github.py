"""GitHub issues as a tracker, over the forge's transport.

Each kit item is an issue carrying the kit's marker as a hidden comment on the last line of its
body. The hierarchy is sub-issues, and a level is an issue type for an organization with types
enabled and a label otherwise. A sub-issue is added by the child's numeric id, which is not its
number, so a create reads the id from the answer.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from pydantic import BaseModel

from agent_build_kit.forges.transport import (
    Credentials,
    NotFound,
    Transport,
    TransportError,
    credential_for,
    validated,
)
from agent_build_kit.settings import settings
from agent_build_kit.trackers.base import (
    STATUS_TAGS,
    Capabilities,
    Item,
    ItemKind,
    UnknownWorkItemType,
    kind_types,
    marker_comment,
    markers_in,
    split_tags,
    without_markers,
)
from agent_build_kit.trackers.config import GithubTracker
from agent_build_kit.trackers.github_models import (
    EventDoc,
    IssueDoc,
    IssueTypeDoc,
    LoginDoc,
    NamedDoc,
    OwnerDoc,
)

# The most sub-issues one parent holds.
SUB_ISSUE_LIMIT = 100
_PAGE = 100
# A status is a label behind this prefix; `active` is the one with no kit tag of its own.
STATUS_PREFIX = "status:"
ACTIVE_LABEL = f"{STATUS_PREFIX}active"
_TAG_LABELS = {f"{STATUS_PREFIX}{tag}" for tag in STATUS_TAGS}
_log = logging.getLogger(__name__)


class SubIssueLimitExceeded(ValueError):
    """A parent that already holds the most sub-issues the host allows: a configuration problem,
    naming the parent, how many it holds and the limit."""

    def __init__(self, parent: str, total: int) -> None:
        super().__init__(
            f"#{parent} holds {total} sub-issues, the most the host allows ({SUB_ISSUE_LIMIT})"
        )
        self.parent = parent
        self.total = total
        self.limit = SUB_ISSUE_LIMIT


class GithubIssues:
    def __init__(self, section: GithubTracker, *, http: httpx.BaseTransport | None = None):
        self._section = section
        self._http = http
        self._transport: Transport | None = None
        self._typed: bool | None = None
        self._levels: dict[ItemKind, str] = kind_types(section.level_types)
        self._login: str | None = None
        self._created_labels: list[str] = []

    def capabilities(self) -> Capabilities:
        return Capabilities(
            hierarchy="native",
            typed=self._has_types(),
            revision_check=False,
        )

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
        if kind not in self._levels:
            raise ValueError(f"kind {kind!r} is not a level of the configuration")
        document: dict[str, Any] = {
            "title": title,
            "body": "\n".join(([body] if body else []) + [self._comment(m) for m in markers]),
        }
        if self._has_types():
            document["type"] = self._levels[kind]
        else:
            document["labels"] = [self._levels[kind]]
        made = self._issue(self._call("POST", self._path(), json=document))
        if parent is not None:
            self._nest(parent, made)
            made = self._issue(self._call("GET", self._path(str(made.number))))
        return self._to_item(made, parent)

    @property
    def created_labels(self) -> tuple[str, ...]:
        """The status labels this tracker made because the repository lacked them."""
        return tuple(self._created_labels)

    def update(
        self, item_id: str, changes: Mapping[str, str], expected_revision: str | None = None
    ) -> Item:
        """Apply `changes` (`title`, `body`, `state`, `tags`). The host has no revision check,
        so `expected_revision` is not read. A state is an open or closed issue with a reason,
        and `active` also carries its label."""
        doc = self._issue(self._call("GET", self._path(item_id)))
        before = {label.name for label in doc.labels}
        labels = set(before)
        patch: dict[str, Any] = {}
        for field, value in changes.items():
            if field == "title":
                patch["title"] = value
            elif field == "body":
                kept = [self._comment(marker) for marker in self._markers_of(doc)]
                patch["body"] = "\n".join(([value] if value else []) + kept)
            elif field == "state":
                patch.update(self._state_patch(value))
                labels.discard(ACTIVE_LABEL)
                if value == "active":
                    labels.add(ACTIVE_LABEL)
            elif field == "tags":
                labels -= _TAG_LABELS
                labels |= {f"{STATUS_PREFIX}{tag}" for tag in split_tags(value)}
            else:
                raise ValueError(f"cannot update {field!r} of an issue")
        if labels != before:
            self._ensure_labels(labels - before)
            patch["labels"] = sorted(labels)
        return self._to_item(self._issue(self._call("PATCH", self._path(item_id), json=patch)))

    def set_tag(self, item_id: str, tag: str, present: bool) -> Item:
        if tag not in STATUS_TAGS:
            raise ValueError(f"{tag!r} is not a status tag ({', '.join(STATUS_TAGS)})")
        label = f"{STATUS_PREFIX}{tag}"
        doc = self._issue(self._call("GET", self._path(item_id)))
        labels = {entry.name for entry in doc.labels} - {label}
        if present:
            labels.add(label)
            self._ensure_labels({label})
        patch = {"labels": sorted(labels)}
        return self._to_item(self._issue(self._call("PATCH", self._path(item_id), json=patch)))

    def claim(self, item_id: str) -> bool:
        """Hold the item by assigning the sync account, then reading the assignments back: the
        earliest assignee wins, and the kit withdraws when it was not first. An issue with
        anyone else on it is not the kit's."""
        me = self._me()
        assigned = self.get(item_id).assignees
        others = [who for who in assigned if who != me]
        if others:
            _log.info("issue #%s is assigned to %s, not claimed", item_id, ", ".join(others))
            return False
        path = self._path(item_id, "assignees")
        if me not in assigned:
            self._call("POST", path, json={"assignees": [me]})
        events = self._list_of(EventDoc, self._path(item_id, "events"))
        first = next((e.assignee.login for e in events if e.event == "assigned" and e.assignee), me)
        if first == me:
            return True
        self._call("DELETE", path, json={"assignees": [me]})
        return False

    def get(self, item_id: str) -> Item:
        return self._to_item(self._issue(self._call("GET", self._path(item_id))))

    def children(self, item_id: str) -> Sequence[Item]:
        docs = self._pages(self._path(item_id, "sub_issues"))
        return [self._to_item(doc, item_id) for doc in docs if self._kind_of(doc) is not None]

    def find_by_marker(self, marker: str) -> Item | None:
        for doc in self._pages(self._path(), state="all"):
            if doc.pull_request is None and marker in self._markers_of(doc):
                return self._to_item(doc)
        return None

    # --- the wire -----------------------------------------------------------------

    def _client(self) -> Transport:
        if self._transport is None:
            credentials: Credentials = credential_for("github", self._section.owner)
            self._transport = Transport(
                settings.github_api_url.rstrip("/"), credentials, transport=self._http
            )
        return self._transport

    def _call(self, method: str, path: str, **options: Any) -> Any:
        return self._client().request(method, path, **options)

    def _path(self, number: str | None = None, rest: str | None = None) -> str:
        base = f"/repos/{self._section.owner}/{self._section.repo}/issues"
        return "/".join(part for part in (base, number, rest) if part)

    def _pages(self, path: str, **params: str) -> list[IssueDoc]:
        return self._list_of(IssueDoc, path, **params)

    def _list_of[Doc: BaseModel](self, model: type[Doc], path: str, **params: str) -> list[Doc]:
        found: list[Doc] = []
        page = 1
        while True:
            reply = self._call(
                "GET", path, params={**params, "per_page": str(_PAGE), "page": str(page)}
            )
            if not isinstance(reply.data, list):
                raise TransportError(f"GET {path}: not a list: {reply.text[:200]}")
            found += [validated(model, entry, path, reply.text) for entry in reply.data]
            if len(reply.data) < _PAGE:
                return found
            page += 1

    def _me(self) -> str:
        if self._login is None:
            reply = self._call("GET", "/user")
            self._login = validated(LoginDoc, reply.data, "user", reply.text).login
        return self._login

    @staticmethod
    def _state_patch(state: str) -> dict[str, str]:
        if state == "done":
            return {"state": "closed", "state_reason": "completed"}
        if state == "removed":
            return {"state": "closed", "state_reason": "not_planned"}
        if state in ("new", "active"):
            return {"state": "open"}
        raise ValueError(f"unknown state {state!r}")

    def _ensure_labels(self, wanted: set[str]) -> None:
        """Make the labels in `wanted` the repository lacks, and note them."""
        if not wanted:
            return
        path = f"/repos/{self._section.owner}/{self._section.repo}/labels"
        have = {label.name for label in self._list_of(NamedDoc, path)}
        for name in sorted(wanted - have):
            self._call("POST", path, json={"name": name})
            self._created_labels.append(name)

    def _issue(self, reply: Any) -> IssueDoc:
        return validated(IssueDoc, reply.data, "issues", reply.text)

    def _has_types(self) -> bool:
        """Whether levels are issue types: the owner is an organization and every configured
        level's type is one of its enabled issue types, read once. An organization missing one
        (or having it disabled) falls back to labels, named as the configuration names the
        levels, so items can still be made."""
        if self._typed is None:
            reply = self._call("GET", f"/users/{self._section.owner}")
            kind = validated(OwnerDoc, reply.data, "users", reply.text).type
            self._typed = kind == "Organization" and self._levels_are_enabled_types()
        return self._typed

    def _levels_are_enabled_types(self) -> bool:
        path = f"/orgs/{self._section.owner}/issue-types"
        try:
            reply = self._call("GET", path)
        except NotFound:
            return False
        if not isinstance(reply.data, list):
            raise TransportError(f"GET {path}: not a list: {reply.text[:200]}")
        listed = (validated(IssueTypeDoc, entry, path, reply.text) for entry in reply.data)
        enabled = {entry.name for entry in listed if entry.is_enabled}
        return bool(self._levels) and set(self._levels.values()) <= enabled

    def _nest(self, parent: str, child: IssueDoc) -> None:
        try:
            self._call(
                "POST",
                self._path(parent, "sub_issues"),
                json={"sub_issue_id": child.id},
            )
        except TransportError as error:
            if error.status != 422:
                raise
            # The issue was made before it could be nested: close it, and take the marker out
            # so a later look-up by marker does not adopt the stray in place of a new item.
            self._call(
                "PATCH",
                self._path(str(child.number)),
                json={
                    "state": "closed",
                    "state_reason": "not_planned",
                    "body": without_markers(self._section.marker_prefix, child.body or "").rstrip(
                        "\n"
                    ),
                },
            )
            # A 422 is the limit when the parent already holds the most the host allows; the
            # parent's own count says so, not the wording of the refusal.
            summary = self._issue(self._call("GET", self._path(parent))).sub_issues_summary
            if summary is None or summary.total < SUB_ISSUE_LIMIT:
                raise
            raise SubIssueLimitExceeded(parent, summary.total) from error

    # --- items --------------------------------------------------------------------

    def _comment(self, marker: str) -> str:
        return marker_comment(self._section.marker_prefix, marker)

    def _markers_of(self, doc: IssueDoc) -> tuple[str, ...]:
        return markers_in(self._section.marker_prefix, doc.body or "")

    def _kind_of(self, doc: IssueDoc) -> ItemKind | None:
        names = {name: kind for kind, name in self._levels.items()}
        named: list[NamedDoc] = [doc.type] if doc.type else list(doc.labels)
        return next((names[entry.name] for entry in named if entry.name in names), None)

    def _to_item(self, doc: IssueDoc, parent: str | None = None) -> Item:
        """`parent` is the issue the caller knows `doc` hangs under, which is not left to the
        host's `parent_issue_url`."""
        kind = self._kind_of(doc)
        if kind is None:
            seen = [doc.type.name] if doc.type else [label.name for label in doc.labels]
            raise UnknownWorkItemType(
                f"issue #{doc.number} has {'type' if doc.type else 'labels'} "
                f"{', '.join(map(repr, seen)) or 'none'}, which no level of the configuration "
                f"uses (levels: {', '.join(self._section.levels)})"
            )
        text = without_markers(self._section.marker_prefix, doc.body or "").rstrip("\n")
        if parent is None and doc.parent_issue_url:
            parent = doc.parent_issue_url.rsplit("/", 1)[-1]
        return Item(
            id=str(doc.number),
            kind=kind,
            title=doc.title,
            body=text,
            state=doc.state,
            assignees=tuple(who.login for who in doc.assignees),
            parent_id=parent,
            revision=doc.updated_at,
            url=doc.html_url,
            markers=self._markers_of(doc),
            tags=tuple(
                label.name.removeprefix(STATUS_PREFIX)
                for label in doc.labels
                if label.name in _TAG_LABELS
            ),
        )
