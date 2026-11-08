"""GitHub issues as a tracker, over the forge's transport.

Each kit item is an issue carrying the kit's marker as a hidden comment on the last line of its
body. The hierarchy is sub-issues, and a level is an issue type for an organization with types
enabled and a label otherwise. A sub-issue is added by the child's numeric id, which is not its
number, so a create reads the id from the answer.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import httpx

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
    Capabilities,
    Item,
    ItemKind,
    UnknownWorkItemType,
    kind_types,
    marker_comment,
    markers_in,
    without_markers,
)
from agent_build_kit.trackers.config import GithubTracker
from agent_build_kit.trackers.github_models import IssueDoc, IssueTypeDoc, NamedDoc, OwnerDoc

# The most sub-issues one parent holds.
SUB_ISSUE_LIMIT = 100
_PAGE = 100


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
        found: list[IssueDoc] = []
        page = 1
        while True:
            reply = self._call(
                "GET", path, params={**params, "per_page": str(_PAGE), "page": str(page)}
            )
            if not isinstance(reply.data, list):
                raise TransportError(f"GET {path}: not a list: {reply.text[:200]}")
            found += [validated(IssueDoc, entry, path, reply.text) for entry in reply.data]
            if len(reply.data) < _PAGE:
                return found
            page += 1

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
        )
