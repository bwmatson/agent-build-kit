"""A group heading may name the project after the repo (spec: unit-projects)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.work_graph import TaskGroup, ValidationError, validate_tasks
from tests.project_workspace import app_with_projects, tasks_with


def read(tmp_path: Path, *headings: str) -> tuple[list[TaskGroup], list[ValidationError]]:
    (tmp_path / "tasks.md").write_text(tasks_with(*headings))
    return validate_tasks(tmp_path / "tasks.md")


def test_a_project_tag_a_nested_project_and_a_plain_tag_are_read_as_their_projects(
    tmp_path: Path,
) -> None:
    app_with_projects(tmp_path / "planning", "web", "services/api")

    groups, errors = read(
        tmp_path,
        "[app/web] [tier1] Add the filter",
        "[app/services/api] [tier1] Add the route",
        "[app] [tier1] Add the marker",
    )

    assert errors == []
    assert [(g.number, g.repo, g.project) for g in groups] == [
        (1, "app", "web"),
        (2, "app", "services/api"),
        (3, "app", "."),
    ]


def test_a_flag_and_a_tier_after_the_project_tag_are_read_as_before(tmp_path: Path) -> None:
    app_with_projects(tmp_path / "planning", "web")

    groups, errors = read(tmp_path, "[app/web] [tier2] [acceptance] Drive the page")

    assert errors == []
    (group,) = groups
    assert (group.project, group.tier, group.flag, group.title) == (
        "web",
        "tier2",
        "acceptance",
        "Drive the page",
    )


def test_a_project_tag_leaves_the_groups_number_title_and_task_count_as_they_are(
    tmp_path: Path,
) -> None:
    app_with_projects(tmp_path / "planning", "web")

    groups, errors = read(tmp_path, "[app] [tier1] First", "[app/web] [tier1] Add the filter")

    assert errors == []
    assert [(g.number, g.title, g.task_count) for g in groups] == [
        (1, "First", 2),
        (2, "Add the filter", 2),
    ]


def test_a_declared_repo_named_with_a_slash_is_read_whole(tmp_path: Path) -> None:
    app_with_projects(tmp_path / "planning", "web", repo="team/app")

    groups, errors = read(
        tmp_path, "[team/app] [tier1] Whole repo", "[team/app/web] [tier1] Its web project"
    )

    assert errors == []
    assert [(g.repo, g.project) for g in groups] == [("team/app", "."), ("team/app", "web")]
