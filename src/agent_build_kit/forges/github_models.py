"""Typed models for the GitHub documents the pipeline reads.

Only the fields the pipeline reads, `extra="ignore"` so a field the host adds
cannot break parsing. The REST documents keep the host's snake_case names; the
GraphQL ones are camelCase on the wire and snake_case here, by alias.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class _Rest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")


class _Graph(BaseModel):
    model_config = ConfigDict(
        frozen=True, extra="ignore", alias_generator=to_camel, populate_by_name=True
    )


# --- REST ---------------------------------------------------------------------


class NumberDoc(_Rest):
    number: int


class PullDoc(_Rest):
    node_id: str
    draft: bool = False


class ReviewDoc(_Rest):
    id: int
    node_id: str = ""
    body: str | None = None


class InlineCommentDoc(_Rest):
    id: int
    node_id: str = ""
    body: str | None = None
    path: str = ""
    line: int | None = None
    pull_request_review_id: int | None = None


class LabelDoc(_Rest):
    name: str
    color: str = ""
    description: str | None = None


class FileDoc(_Rest):
    filename: str


class JobDoc(_Rest):
    id: int
    name: str = ""
    conclusion: str | None = None


class JobsDoc(_Rest):
    jobs: list[JobDoc] = []


class StackPullDoc(_Rest):
    number: int


class StackDoc(_Rest):
    number: int
    open: bool = False
    pull_requests: list[StackPullDoc] | None = None


class NodeIdDoc(_Rest):
    node_id: str = ""


# --- GraphQL ------------------------------------------------------------------


class Connection[Node](_Graph):
    nodes: list[Node] = []


class NamedNode(_Graph):
    name: str


class CommentNode(_Graph):
    id: str
    body: str | None = None


class ReviewNode(_Graph):
    id: str
    state: str = ""


class CheckNode(_Graph):
    """A rollup context. A commit status is one too, with none of these."""

    typename: str = Field("", alias="__typename")
    name: str | None = None
    conclusion: str | None = None
    details_url: str | None = None


class RollupNode(_Graph):
    contexts: Connection[CheckNode] | None = None


class CommitNode(_Graph):
    status_check_rollup: RollupNode | None = None


class CommitEdge(_Graph):
    commit: CommitNode


class PullNode(_Graph):
    number: int
    head_ref_name: str = ""
    base_ref_name: str = ""
    state: str = ""
    is_draft: bool = False
    merged_at: str | None = None
    mergeable: str | None = None
    review_decision: str | None = None
    labels: Connection[NamedNode] | None = None
    comments: Connection[CommentNode] | None = None
    reviews: Connection[ReviewNode] | None = None
    commits: Connection[CommitEdge] | None = None


class PageInfo(_Graph):
    has_next_page: bool = False
    end_cursor: str | None = None


class PullConnection(_Graph):
    page_info: PageInfo = PageInfo()
    nodes: list[PullNode] = []


class ChecksPull(_Graph):
    commits: Connection[CommitEdge] | None = None
