"""A project the repo does not declare is refused, naming what it declares (spec: unit-projects)."""

from __future__ import annotations

from pathlib import Path

from agent_build_kit.pipeline.work_graph import validate_tasks
from tests.project_workspace import app_with_projects, tasks_with


def messages_of(tmp_path: Path, *headings: str) -> list[str]:
    (tmp_path / "tasks.md").write_text(tasks_with(*headings))
    return [error.message for error in validate_tasks(tmp_path / "tasks.md")[1]]


def test_an_undeclared_project_is_refused_naming_the_group_project_repo_and_declared_ones(
    tmp_path: Path,
) -> None:
    app_with_projects(tmp_path / "planning", "web", "services/api")

    (message,) = messages_of(tmp_path, "[app/mobile] [tier1] Add the screen")

    assert "group 1" in message
    assert "mobile" in message
    assert "app" in message
    assert "web" in message
    assert "services/api" in message


def test_a_repo_with_only_its_root_says_so_and_how_the_root_is_tagged(tmp_path: Path) -> None:
    app_with_projects(tmp_path / "planning")

    (message,) = messages_of(tmp_path, "[app/web] [tier1] Add the filter")

    assert "only its root project" in message
    assert "[app]" in message


def test_the_root_project_is_never_written_in_a_tag(tmp_path: Path) -> None:
    app_with_projects(tmp_path / "planning", "web")

    (message,) = messages_of(tmp_path, "[app/.] [tier1] Add the marker")

    assert "root project is the untagged one" in message


def test_an_unknown_repo_gets_the_unknown_repo_message_and_not_a_project_one(
    tmp_path: Path,
) -> None:
    app_with_projects(tmp_path / "planning", "web")

    (message,) = messages_of(tmp_path, "[nothing/web] [tier1] Add the filter")

    assert 'unknown repo "nothing"' in message
    assert "platform" in message
    assert "project" not in message


def test_every_problem_is_collected_not_the_first(tmp_path: Path) -> None:
    app_with_projects(tmp_path / "planning", "web")

    messages = messages_of(
        tmp_path,
        "[app/mobile] [tier1] One",
        "[app/web] [tier1] Fine",
        "[app/.] [tier1] Two",
        "[nothing] [tier1] Three",
    )

    # A refused group is not parsed, so the numbering check adds its own message.
    for group in ("group 1", "group 3", "group 4"):
        assert any(group in message for message in messages)
