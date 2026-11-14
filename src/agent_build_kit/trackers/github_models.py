"""Typed models for the GitHub documents the issues tracker reads.

Only the fields the tracker reads, `extra="ignore"` so a field the host adds cannot break
parsing.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class _Doc(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class NamedDoc(_Doc):
    name: str


class LoginDoc(_Doc):
    login: str


class OwnerDoc(_Doc):
    type: str


class SubIssuesSummaryDoc(_Doc):
    total: int


class IssueDoc(_Doc):
    id: int
    number: int
    title: str
    body: str | None = None
    state: str
    state_reason: str | None = None
    html_url: str
    updated_at: str = ""
    labels: tuple[NamedDoc, ...] = ()
    type: NamedDoc | None = None
    assignees: tuple[LoginDoc, ...] = ()
    parent_issue_url: str | None = None
    sub_issues_summary: SubIssuesSummaryDoc | None = None
    # Present only on a pull request, which the issues list also returns.
    pull_request: dict[str, object] | None = None


class EventDoc(_Doc):
    """One entry of an issue's event list; `assignee` is set on an assignment."""

    event: str
    assignee: LoginDoc | None = None
    actor: LoginDoc | None = None
    created_at: str = ""


class IssueTypeDoc(_Doc):
    name: str
    is_enabled: bool = True


class LastEditDoc(_Doc):
    """When an issue's title or body was last edited, and by whom."""

    lastEditedAt: str | None = None  # noqa: N815 - the host's own name
    editor: LoginDoc | None = None


class _EditedRepositoryDoc(_Doc):
    issue: LastEditDoc | None = None


class _EditedDataDoc(_Doc):
    repository: _EditedRepositoryDoc


class LastEditAnswerDoc(_Doc):
    """The answer to the last-edit GraphQL query."""

    data: _EditedDataDoc
