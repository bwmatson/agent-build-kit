"""Build slots are counted for each project: units being built in one take none from another."""

from __future__ import annotations

from agent_build_kit.pipeline.units import IN_REVIEW, RUNNING
from tests.factories import new_unit as new
from tests.factories import started_ids


def building(prefix: str, project: str, count: int):
    return [
        new(
            f"{prefix}{n}/1",
            state=RUNNING,
            repo="app",
            project=project,
            branch=f"spec/{prefix}{n}/1",
        )
        for n in range(count)
    ]


def ready(prefix: str, project: str, count: int):
    return [new(f"{prefix}{n}/1", repo="app", project=project) for n in range(count)]


def blocked_web_unit():
    """A started `web` unit waiting on `dep/1`, so it is uncounted and frees a place."""
    return new(
        "blocked/1", repo="app", project="web", branch="spec/blocked/1", depends_on=("dep/1",)
    )


def test_two_projects_with_four_ready_units_each_start_eight_on_four_slots() -> None:
    graph = [*ready("w", "web", 4), *ready("p", "api", 4)]

    assert len(started_ids(graph, slots=4)) == 8


def test_a_project_with_busy_slots_starts_none_and_another_starts_its_free_ones() -> None:
    graph = [
        *building("wb", "web", 4),
        *building("pb", "api", 1),
        *ready("w", "web", 2),
        *ready("p", "api", 5),
    ]

    assert sorted(started_ids(graph, slots=4)) == ["p0/1", "p1/1", "p2/1"]


def test_a_project_with_two_building_and_three_ready_on_four_slots_starts_two() -> None:
    graph = [*building("b", "web", 2), *ready("r", "web", 3)]

    assert len(started_ids(graph, slots=4)) == 2


def test_a_blocked_units_place_goes_to_a_ready_unit_of_its_own_project() -> None:
    graph = [
        blocked_web_unit(),
        new("dep/1", repo="app", project="web"),
        new("api1/1", repo="app", project="api"),
    ]

    ids = started_ids(graph, slots=2, max_units_in_progress=1)

    assert sorted(ids) == ["api1/1", "dep/1"]


def test_a_blocked_units_place_is_not_given_to_a_ready_unit_of_a_full_project() -> None:
    graph = [
        new("api0/1", state=IN_REVIEW, pr=1, repo="app", project="api"),
        blocked_web_unit(),
        new("dep/1", repo="app", project="api"),
        new("web1/1", repo="app", project="web"),
    ]

    assert started_ids(graph, slots=3, max_units_in_progress=1) == ["web1/1"]
