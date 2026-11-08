"""Typed models for the Azure DevOps work item documents the tracker reads.

Only the fields the tracker reads, `extra="ignore"` so a field the host adds cannot break
parsing. A work item's fields are keyed by their reference names (`System.Title`).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Doc(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)


class IdentityDoc(_Doc):
    unique_name: str = Field(alias="uniqueName")
    display_name: str = Field(default="", alias="displayName")


class FieldsDoc(_Doc):
    type: str = Field(alias="System.WorkItemType")
    title: str = Field(alias="System.Title")
    state: str = Field(alias="System.State")
    description: str = Field(default="", alias="System.Description")
    tags: str = Field(default="", alias="System.Tags")
    assigned_to: IdentityDoc | None = Field(default=None, alias="System.AssignedTo")
    changed_date: str = Field(default="", alias="System.ChangedDate")
    changed_by: IdentityDoc | None = Field(default=None, alias="System.ChangedBy")


class RelationDoc(_Doc):
    rel: str
    url: str


class LinkDoc(_Doc):
    href: str


class LinksDoc(_Doc):
    html: LinkDoc | None = None


class WorkItemDoc(_Doc):
    id: int
    rev: int
    fields: FieldsDoc
    relations: tuple[RelationDoc, ...] = ()
    url: str
    links: LinksDoc | None = Field(default=None, alias="_links")


class WorkItemsDoc(_Doc):
    # `errorPolicy=Omit` answers null for an id that no longer exists.
    value: tuple[WorkItemDoc | None, ...] = ()


class WiqlRefDoc(_Doc):
    id: int


class WiqlDoc(_Doc):
    # When the service answered the query: an item with a later change date was edited since.
    as_of: str = Field(default="", alias="asOf")
    work_items: tuple[WiqlRefDoc, ...] = Field(default=(), alias="workItems")


class ProjectRefDoc(_Doc):
    id: str


class RepositoryDoc(_Doc):
    id: str
    project: ProjectRefDoc


class PropertyDoc(_Doc):
    value: str = Field(default="", alias="$value")


class AuthenticatedUserDoc(_Doc):
    properties: dict[str, PropertyDoc] = {}


class ConnectionDataDoc(_Doc):
    authenticated_user: AuthenticatedUserDoc = Field(alias="authenticatedUser")


class UpdateDoc(_Doc):
    """One revision of a work item: the fields it changed, each with the value it set."""

    fields: dict[str, object] = {}


class NamedDoc(_Doc):
    name: str


class StateDoc(_Doc):
    name: str


class WorkItemTypeDoc(_Doc):
    name: str
    states: tuple[StateDoc, ...] = ()


class WorkItemTypesDoc(_Doc):
    value: tuple[WorkItemTypeDoc, ...] = ()


class BacklogDoc(_Doc):
    """One backlog level. `rank` orders the levels, the highest for the top of the nesting; the
    order of the list says nothing."""

    rank: int
    work_item_types: tuple[NamedDoc, ...] = Field(default=(), alias="workItemTypes")


class BacklogsDoc(_Doc):
    value: tuple[BacklogDoc, ...] = ()
