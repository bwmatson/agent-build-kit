"""`start_room` is the room of one project: only that project's units in progress count."""

from __future__ import annotations

from agent_build_kit.pipeline.units import (
    FAILED,
    IN_REVIEW,
    RUNNING,
    ProjectKey,
    start_room,
)
from tests.factories import new_unit as new

WEB = ProjectKey(repo="app", project="web")
API = ProjectKey(repo="app", project="api")


def review(uid: str, project: str):
    return new(uid, state=IN_REVIEW, pr=1, repo="app", project=project)


def test_the_room_of_a_project_counts_only_that_projects_units_in_progress() -> None:
    graph = [review("a/1", "web"), review("a/2", "web"), review("b/1", "api")]

    assert start_room(graph, 5, WEB) == 3
    assert start_room(graph, 5, API) == 4


def test_a_blocked_unit_is_uncounted_in_its_own_project() -> None:
    graph = [
        new("base/1", state=RUNNING, repo="app", project="web"),
        new("next/1", repo="app", project="web", branch="spec/next/1", depends_on=("base/1",)),
        review("other/1", "api"),
    ]

    assert start_room(graph, 2, WEB) == 1
    assert start_room(graph, 2, API) == 1


def test_a_failed_unit_that_waits_is_uncounted_in_its_own_project() -> None:
    graph = [
        review("base/1", "web"),
        new(
            "next/1",
            state=FAILED,
            repo="app",
            project="api",
            branch="spec/next/1",
            depends_on=("gate/1",),
        ),
        new("gate/1", state=RUNNING, repo="app", project="web"),
    ]

    assert start_room(graph, 2, API) == 2
    assert start_room(graph, 2, WEB) == 0
