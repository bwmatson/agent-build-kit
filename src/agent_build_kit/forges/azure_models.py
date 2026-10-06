"""Typed models for the Azure DevOps REST documents the pipeline reads.

Only the fields the pipeline reads, `extra="ignore"` so a field the host adds
cannot break parsing. Attribute names are snake_case; the host's camelCase names
are their aliases.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class _Doc(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="ignore", alias_generator=to_camel, populate_by_name=True
    )


class ProjectDoc(_Doc):
    id: str


class RepositoryDoc(_Doc):
    project: ProjectDoc


class ReviewerDoc(_Doc):
    vote: int
    is_container: bool | None = None


class LabelDoc(_Doc):
    name: str


class PullRequestDoc(_Doc):
    pull_request_id: int
    status: str
    merge_status: str | None = None
    is_draft: bool = False
    source_ref_name: str
    target_ref_name: str
    labels: list[LabelDoc] | None = None
    reviewers: list[ReviewerDoc] = []
    repository: RepositoryDoc


class CommentDoc(_Doc):
    id: int
    content: str | None = None
    comment_type: str | None = None
    is_deleted: bool | None = None


class PositionDoc(_Doc):
    line: int | None = None


class ThreadContextDoc(_Doc):
    file_path: str | None = None
    right_file_start: PositionDoc | None = None


class ThreadDoc(_Doc):
    id: int
    status: str | None = None
    comments: list[CommentDoc] = []
    thread_context: ThreadContextDoc | None = None


class PolicyTypeDoc(_Doc):
    id: str
    display_name: str | None = None


class PolicyConfigurationDoc(_Doc):
    type: PolicyTypeDoc
    settings: dict[str, Any] = {}


class EvaluationContextDoc(_Doc):
    build_id: int | None = None


class EvaluationDoc(_Doc):
    evaluation_id: str
    status: str
    configuration: PolicyConfigurationDoc
    context: EvaluationContextDoc | None = None


class StatusContextDoc(_Doc):
    genre: str | None = None
    name: str


class StatusDoc(_Doc):
    id: int
    state: str
    description: str | None = None
    target_url: str | None = None
    context: StatusContextDoc


class BuildDoc(_Doc):
    id: int
    build_number: str | None = None
    result: str | None = None


class IterationDoc(_Doc):
    id: int


class ChangeItemDoc(_Doc):
    path: str | None = None
    is_folder: bool | None = None


class ChangeDoc(_Doc):
    item: ChangeItemDoc | None = None


class ChangesDoc(_Doc):
    change_entries: list[ChangeDoc] | None = None
    next_skip: int = 0
    next_top: int = 0


class RefDoc(_Doc):
    name: str
    object_id: str | None = None


class RefUpdateDoc(_Doc):
    """One ref's outcome in the answer to an update: refused ones are a 200 too."""

    name: str = ""
    success: bool = False
    update_status: str | None = None
