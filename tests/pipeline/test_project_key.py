"""A unit is counted in its repo's project; the counts are grouped by that key, with no total."""

from __future__ import annotations

from agent_build_kit.pipeline.units import (
    IN_REVIEW,
    ProjectKey,
    project_counts,
    project_key,
)
from tests.factories import new_unit as new


def review(uid: str, **kw):
    return new(uid, state=IN_REVIEW, pr=1, **kw)


def test_a_units_key_is_its_repo_and_its_project() -> None:
    key = project_key(new("a/1", repo="app", project="web"))

    assert key == ProjectKey(repo="app", project="web")


def test_a_unit_with_no_project_is_in_the_root_project() -> None:
    assert project_key(new("a/1", repo="app")) == ProjectKey(repo="app", project=".")


def test_two_projects_of_one_repo_and_two_repos_are_four_keys() -> None:
    units = [
        new("a/1", repo="app", project="."),
        new("b/1", repo="app", project="web"),
        new("c/1", repo="platform", project="."),
        new("d/1", repo="platform", project="web"),
    ]

    assert len({project_key(unit) for unit in units}) == 4


def test_a_unit_of_an_undeclared_project_is_a_key_of_its_own() -> None:
    graph = [review("a/1", repo="app", project="old"), review("b/1", repo="app")]

    assert project_counts(graph) == {
        ProjectKey(repo="app", project="old"): 1,
        ProjectKey(repo="app", project="."): 1,
    }


def test_counts_are_grouped_by_key_and_no_total_exists() -> None:
    graph = [
        review("a/1", repo="app", project="web"),
        review("a/2", repo="app", project="web"),
        review("b/1", repo="app"),
        review("c/1", repo="platform"),
        new("d/1", repo="app", project="web"),
    ]

    assert project_counts(graph) == {
        ProjectKey(repo="app", project="web"): 2,
        ProjectKey(repo="app", project="."): 1,
        ProjectKey(repo="platform", project="."): 1,
    }
