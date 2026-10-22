"""Every dependency edge has a kind: `merge` in three cases, `review` otherwise
(spec: needs-can-wait-for-a-merge)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent_build_kit.config import RepoConfig
from agent_build_kit.pipeline.unit_store import RequeueReason
from agent_build_kit.pipeline.units import (
    FAILED,
    IN_REVIEW,
    MERGED,
    PLANNED,
    RUNNING,
    EdgeKind,
    UnitState,
    edge_kind,
)
from tests.conftest import make_installation
from tests.factories import stored_unit


@pytest.fixture
def repos(tmp_path: Path) -> dict[str, RepoConfig]:
    return make_installation(tmp_path).repos


def pair(parent_change: str = "base", **dependent):
    """A parent unit of `parent_change` and a dependent of `feature` that depends on it."""
    parent = stored_unit(f"{parent_change}/1", change=parent_change)
    fields = {"change": "feature", "depends_on": (parent.id,), **dependent}
    return stored_unit("feature/1", **fields), parent


def test_an_edge_across_repositories_is_a_merge_edge_with_its_reason(repos) -> None:
    child, parent = pair(repo="app")
    parent = parent.model_copy(update={"repo": "platform"})

    edge = edge_kind(child, parent, repos)

    assert edge.kind is EdgeKind.MERGE
    assert edge.reason == "another repository"


def test_an_edge_the_author_wrote_merged_is_a_merge_edge_with_its_reason(repos) -> None:
    child, parent = pair()
    child = child.model_copy(update={"needs": (parent.id,), "merge_needs": (parent.id,)})

    edge = edge_kind(child, parent, repos)

    assert edge.kind is EdgeKind.MERGE
    assert edge.reason == "the Needs: line says merged"


def test_an_edge_of_a_failed_unit_is_a_merge_edge_with_its_reason(repos) -> None:
    child, parent = pair(state=FAILED)

    edge = edge_kind(child, parent, repos)

    assert edge.kind is EdgeKind.MERGE
    assert edge.reason == "a failed unit resumes after the fix is merged"


def test_an_edge_of_a_planned_unit_with_a_gated_requeue_is_a_merge_edge(repos) -> None:
    """A failed unit a person requeued while it waited is parked planned with its requeue saved."""
    child, parent = pair(state=PLANNED, gated_requeue=RequeueReason.RESUME)

    assert edge_kind(child, parent, repos).kind is EdgeKind.MERGE


def test_a_planned_dependent_on_a_plain_same_repo_needs_is_a_review_edge(repos) -> None:
    child, parent = pair()
    child = child.model_copy(update={"needs": (parent.id,)})

    assert edge_kind(child, parent, repos).kind is EdgeKind.REVIEW


def test_a_parent_in_the_kits_repository_of_another_change_is_a_review_edge(repos) -> None:
    """Authors write `merged` for those edges; no rule forces it."""
    child, parent = pair(parent_change="other")

    assert edge_kind(child, parent, repos).kind is EdgeKind.REVIEW


def test_an_e2e_unit_of_a_repo_without_a_dev_stack_is_a_review_edge(repos) -> None:
    assert repos["app"].dev_stack is None
    child, parent = pair(tier="e2e-test")

    assert edge_kind(child, parent, repos).kind is EdgeKind.REVIEW


@pytest.mark.parametrize("state", [PLANNED, RUNNING, IN_REVIEW, MERGED, UnitState.HELD])
def test_a_plans_plain_depends_on_an_authors_merge_parent_stays_a_merge_edge(
    repos, state: UnitState
) -> None:
    """The planner writes plain edges and cannot loosen the author's kind: the unit's
    `depends_on` is the plan's, `merge_needs` the author's, and a replan keeps the latter
    for a started unit as for a planned one."""
    child, parent = pair(state=state)
    child = child.model_copy(update={"needs": (parent.id,), "merge_needs": (parent.id,)})

    assert edge_kind(child, parent, repos).kind is EdgeKind.MERGE
