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


class FieldsDoc(_Doc):
    type: str = Field(alias="System.WorkItemType")
    title: str = Field(alias="System.Title")
    state: str = Field(alias="System.State")
    description: str = Field(default="", alias="System.Description")
    tags: str = Field(default="", alias="System.Tags")
    assigned_to: IdentityDoc | None = Field(default=None, alias="System.AssignedTo")


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
    value: tuple[WorkItemDoc, ...] = ()


class WiqlRefDoc(_Doc):
    id: int


class WiqlDoc(_Doc):
    work_items: tuple[WiqlRefDoc, ...] = Field(default=(), alias="workItems")


class PropertyDoc(_Doc):
    value: str = Field(default="", alias="$value")


class AuthenticatedUserDoc(_Doc):
    properties: dict[str, PropertyDoc] = {}


class ConnectionDataDoc(_Doc):
    authenticated_user: AuthenticatedUserDoc = Field(alias="authenticatedUser")
